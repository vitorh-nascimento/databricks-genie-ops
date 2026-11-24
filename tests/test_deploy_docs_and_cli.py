"""Testes de deploy seguro (backup/rollback), diff remoto, geração de docs e comandos CLI."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from typer.testing import CliRunner

from genieops.benchmark import run_benchmark
from genieops.cli import app
from genieops.compiler import compile_space
from genieops.deployer import compute_remote_diff, deploy_space
from genieops.docs_generator import _production_readiness_status, generate_docs
from genieops.history import HistoryStore
from genieops.linter import lint_space
from genieops.models import SpaceBundle
from tests.conftest import REPO_ROOT, FakeCompletedProcess, make_json_response


def test_deploy_update_creates_backup_and_diff_detects_changes(
    exemplo_bundle: SpaceBundle, tmp_path: Path, mock_client_factory
) -> None:
    old_remote_payload = compile_space(exemplo_bundle)
    old_remote_payload["instructions"]["text_instructions"][0]["content"] = ["Regra antiga"]

    def handler(cmd: list[str]) -> FakeCompletedProcess:
        if "list-spaces" in cmd:
            return make_json_response(
                {"spaces": [{"space_id": "sp_existing_1", "title": exemplo_bundle.space.title}]}
            )
        if "get-space" in cmd:
            return make_json_response(
                {
                    "space_id": "sp_existing_1",
                    "title": exemplo_bundle.space.title,
                    "serialized_space": json.dumps(old_remote_payload),
                }
            )
        if "update-space" in cmd:
            return make_json_response({"space_id": "sp_existing_1"})
        return make_json_response({})

    client, runner = mock_client_factory(handler)

    # 1. Diff deve detectar mudança em text_instructions
    diff, sid = compute_remote_diff(exemplo_bundle, env_name="dev", client=client, base_dir=REPO_ROOT)
    assert sid == "sp_existing_1"
    assert diff.has_changes is True
    assert any("text_instructions" in s for s in diff.summary)

    # 2. Deploy deve salvar backup automático e chamar update-space
    res = deploy_space(
        exemplo_bundle,
        env_name="dev",
        client=client,
        base_dir=REPO_ROOT,
        state_dir=tmp_path / ".genieops",
    )
    assert res.action == "UPDATE"
    assert res.space_id == "sp_existing_1"
    assert res.backup_path is not None and res.backup_path.exists()
    assert any("update-space" in c for c in runner.calls)


def test_deploy_create_flow(
    exemplo_bundle: SpaceBundle, tmp_path: Path, mock_client_factory
) -> None:
    def handler(cmd: list[str]) -> FakeCompletedProcess:
        if "list-spaces" in cmd:
            return make_json_response({"spaces": []})
        if "get-default-warehouse" in cmd:
            return make_json_response({"warehouse_id": "wh_auto_99"})
        if "mkdirs" in cmd:
            return FakeCompletedProcess(returncode=0, stdout="")
        if "create-space" in cmd:
            return make_json_response({"space_id": "sp_new_77"})
        return make_json_response({})

    client, runner = mock_client_factory(handler)
    res = deploy_space(
        exemplo_bundle,
        env_name="dev",
        client=client,
        base_dir=REPO_ROOT,
        state_dir=tmp_path / ".genieops",
    )
    assert res.action == "CREATE"
    assert res.space_id == "sp_new_77"
    assert any("mkdirs" in c for c in runner.calls)
    assert any("create-space" in c for c in runner.calls)


def test_generate_docs_creates_all_four_artifacts(
    exemplo_bundle: SpaceBundle, tmp_path: Path
) -> None:
    history = HistoryStore(db_path=tmp_path / "history.db")
    run_benchmark(exemplo_bundle, env_name="dev", mode="offline", history=history)

    out_dir = tmp_path / "docs"
    outputs = generate_docs(exemplo_bundle, output_dir=out_dir, history=history)
    assert set(outputs.keys()) == {
        "spec_tecnica",
        "relatorio_executivo_md",
        "relatorio_executivo_html",
        "guia_usuario",
    }
    for path in outputs.values():
        assert path.exists()
        assert path.stat().st_size > 200

    spec_text = outputs["spec_tecnica"].read_text(encoding="utf-8")
    assert "```mermaid" in spec_text
    assert "fct_pedidos" in spec_text
    assert "mv_kpis_comerciais" in spec_text

    html_text = outputs["relatorio_executivo_html"].read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html_text
    assert "100.0%" in html_text
    # Rodada offline não mede o Genie real: nunca pode aprovar para produção.
    assert "APROVADO PARA PRODUÇÃO" not in html_text
    assert "Apenas Validação Offline" in html_text


def test_readiness_requires_non_offline_run(exemplo_bundle: SpaceBundle, tmp_path: Path) -> None:
    history = HistoryStore(db_path=tmp_path / "history.db")
    offline_run, _ = run_benchmark(exemplo_bundle, env_name="dev", mode="offline", history=history)
    lint_report = lint_space(exemplo_bundle)

    label, css = _production_readiness_status(lint_report, offline_run)
    assert "Offline" in label and css == "warning"

    live_ok = replace(offline_run, mode="live", accuracy_pct=92.0)
    assert _production_readiness_status(lint_report, live_ok) == ("APROVADO PARA PRODUÇÃO", "success")

    live_mid = replace(offline_run, mode="live", accuracy_pct=80.0)
    assert _production_readiness_status(lint_report, live_mid)[1] == "warning"

    live_low = replace(offline_run, mode="agent", accuracy_pct=60.0)
    assert _production_readiness_status(lint_report, live_low)[1] == "danger"


def test_cli_end_to_end_commands(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(REPO_ROOT)
    cli_runner = CliRunner()

    r_list = cli_runner.invoke(app, ["list"])
    assert r_list.exit_code == 0
    assert "exemplo_vendas" in r_list.stdout

    r_lint = cli_runner.invoke(app, ["lint", "exemplo_vendas", "--strict"])
    assert r_lint.exit_code == 0
    assert "Health Score" in r_lint.stdout

    compiled_file = tmp_path / "compiled_prod.json"
    r_compile = cli_runner.invoke(
        app, ["compile", "exemplo_vendas", "--env", "prod", "--output", str(compiled_file)]
    )
    assert r_compile.exit_code == 0
    assert compiled_file.exists()
    data = json.loads(compiled_file.read_text(encoding="utf-8"))
    assert data["data_sources"]["tables"][0]["identifier"].startswith("analytics_prod.")

    # Testa init em diretório temporário isolado
    monkeypatch.chdir(tmp_path)
    r_init = cli_runner.invoke(app, ["init", "novo_dominio", "--title", "Novo Domínio"])
    assert r_init.exit_code == 0
    assert (tmp_path / "spaces" / "novo_dominio" / "space.yaml").exists()
    assert (tmp_path / "spaces" / "novo_dominio" / "benchmarks.yaml").exists()
