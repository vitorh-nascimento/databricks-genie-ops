"""Orquestração de deploy seguro (com backup automático/rollback) e diff contra o Genie remoto."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from genieops.compiler import PayloadDiff, compile_space, diff_payloads, serialize_compact
from genieops.databricks_client import DatabricksClient
from genieops.linter import LintReport, lint_space
from genieops.loader import resolve_env_config, save_space
from genieops.migrator import remap_space_bundle
from genieops.models import EnvironmentConfig, SpaceBundle


@dataclass
class DeployResult:
    action: str  # CREATE | UPDATE | DRY_RUN | BLOCKED_BY_LINT
    space_id: str | None
    env: str
    backup_path: Path | None = None
    lint_report: LintReport | None = None
    payload_path: Path | None = None
    message: str = ""


def _resolve_target_bundle(
    bundle: SpaceBundle,
    env_name: str,
    base_dir: Path | None = None,
) -> tuple[SpaceBundle, EnvironmentConfig]:
    """Resolve config do ambiente alvo e aplica remapeamento caso difira do default_env."""
    default_env_cfg = resolve_env_config(bundle, bundle.space.default_env, base_dir=base_dir)
    target_env_cfg = resolve_env_config(bundle, env_name, base_dir=base_dir)
    if target_env_cfg.name != default_env_cfg.name:
        remapped, _ = remap_space_bundle(bundle, default_env_cfg, target_env_cfg)
        return remapped, target_env_cfg
    return bundle, target_env_cfg


def _find_remote_space_id(
    bundle: SpaceBundle,
    env_cfg: EnvironmentConfig,
    client: DatabricksClient,
) -> str | None:
    if env_cfg.space_id:
        return env_cfg.space_id
    for sp in client.list_spaces():
        if sp.get("title") == bundle.space.title:
            return sp.get("space_id")
    return None


def _extract_remote_payload(remote_space: dict[str, Any]) -> dict[str, Any]:
    raw_ss = remote_space.get("serialized_space")
    if isinstance(raw_ss, str):
        return json.loads(raw_ss)
    if isinstance(raw_ss, dict):
        return raw_ss
    return {}


def compute_remote_diff(
    bundle: SpaceBundle,
    env_name: str,
    client: DatabricksClient,
    base_dir: Path | None = None,
) -> tuple[PayloadDiff, str | None]:
    """Compara o payload compilado local com o Genie Space remoto no ambiente especificado."""
    target_bundle, env_cfg = _resolve_target_bundle(bundle, env_name, base_dir=base_dir)
    local_payload = compile_space(target_bundle)
    space_id = _find_remote_space_id(target_bundle, env_cfg, client)
    if not space_id:
        return (
            PayloadDiff(
                has_changes=True,
                unified_diff="",
                summary=[f"Space '{bundle.space.title}' ainda não existe no ambiente '{env_name}' (será criado)."],
            ),
            None,
        )
    remote_space = client.get_space(space_id, include_serialized_space=True)
    remote_payload = _extract_remote_payload(remote_space)
    return diff_payloads(local_payload, remote_payload), space_id


def deploy_space(
    bundle: SpaceBundle,
    env_name: str,
    client: DatabricksClient,
    base_dir: Path | None = None,
    state_dir: Path | None = None,
    dry_run: bool = False,
    skip_lint: bool = False,
    persist_space_id: bool = False,
) -> DeployResult:
    """
    Valida (linter), compila e realiza create-space ou update-space no Databricks.
    Antes de qualquer update-space, salva backup automático JSON da versão anterior para rollback.
    """
    target_bundle, env_cfg = _resolve_target_bundle(bundle, env_name, base_dir=base_dir)
    l_report = lint_space(target_bundle)

    if not skip_lint and not l_report.passed:
        return DeployResult(
            action="BLOCKED_BY_LINT",
            space_id=env_cfg.space_id,
            env=env_name,
            lint_report=l_report,
            message=f"Deploy bloqueado: {l_report.error_count} erro(s) encontrado(s) no linter.",
        )

    payload = compile_space(target_bundle)
    compact = serialize_compact(payload)

    s_dir = state_dir or ((base_dir or Path.cwd()) / ".genieops")
    staging_path = s_dir / "staging" / f"{bundle.space.name}_{env_name}.json"
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    if dry_run:
        return DeployResult(
            action="DRY_RUN",
            space_id=env_cfg.space_id,
            env=env_name,
            lint_report=l_report,
            payload_path=staging_path,
            message=f"Dry-run concluído. Payload determinístico salvo em {staging_path}.",
        )

    existing_id = _find_remote_space_id(target_bundle, env_cfg, client)
    backup_path: Path | None = None

    if existing_id:
        # Backup automático antes de sobrescrever (full replacement)
        remote_space = client.get_space(existing_id, include_serialized_space=True)
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_path = s_dir / "backups" / bundle.space.name / env_name / f"{existing_id}_{ts}.json"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(
            json.dumps(remote_space, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        client.update_space(
            space_id=existing_id,
            serialized_space_compact=compact,
            title=target_bundle.space.title,
            description=target_bundle.space.description,
        )
        return DeployResult(
            action="UPDATE",
            space_id=existing_id,
            env=env_name,
            backup_path=backup_path,
            lint_report=l_report,
            payload_path=staging_path,
            message=f"Genie Space '{existing_id}' atualizado com sucesso no ambiente '{env_name}'.",
        )

    # Create flow
    warehouse_id = env_cfg.warehouse_id
    if not warehouse_id or warehouse_id.startswith("<"):
        warehouse_id = client.get_default_warehouse()
    if not warehouse_id:
        raise ValueError(
            f"warehouse_id não configurado para o ambiente '{env_name}' e nenhum default warehouse encontrado."
        )

    if env_cfg.parent_path:
        client.ensure_parent_path(env_cfg.parent_path)

    created = client.create_space(
        warehouse_id=warehouse_id,
        serialized_space_compact=compact,
        title=target_bundle.space.title,
        description=target_bundle.space.description,
        parent_path=env_cfg.parent_path,
    )
    new_space_id = created.get("space_id")

    if persist_space_id and new_space_id:
        bundle.space.environments.setdefault(env_name, EnvironmentConfig(name=env_name))
        bundle.space.environments[env_name].space_id = new_space_id
        save_space(bundle, base_dir=base_dir)

    return DeployResult(
        action="CREATE",
        space_id=new_space_id,
        env=env_name,
        lint_report=l_report,
        payload_path=staging_path,
        message=f"Novo Genie Space criado com sucesso no ambiente '{env_name}' (ID: {new_space_id}).",
    )
