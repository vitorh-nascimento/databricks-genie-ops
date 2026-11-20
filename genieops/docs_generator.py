"""Gerador automático de documentação técnica, relatório executivo (MD/HTML) e guia do usuário."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from genieops.history import BenchmarkRunRecord, HistoryStore, RegressionDiff
from genieops.linter import LintReport, lint_space
from genieops.models import SpaceBundle


def _default_templates_dir() -> Path:
    # Suporta execução tanto a partir do repositório quanto instalado
    repo_candidate = Path(__file__).resolve().parent.parent / "templates"
    if repo_candidate.exists():
        return repo_candidate
    cwd_candidate = Path.cwd() / "templates"
    if cwd_candidate.exists():
        return cwd_candidate
    raise FileNotFoundError("Diretório de templates Jinja2 ('templates/') não encontrado.")


def _production_readiness_status(
    lint_report: LintReport,
    latest_run: BenchmarkRunRecord | None,
) -> tuple[str, str]:
    """Retorna (badge_label, css_class) indicando prontidão para produção."""
    if lint_report.error_count > 0:
        return ("BLOQUEADO — Erros de Linter", "danger")
    if latest_run is None:
        return ("EM HOMOLOGAÇÃO — Sem Benchmark", "warning")
    if latest_run.accuracy_pct >= 90.0 and lint_report.health_score >= 85:
        return ("APROVADO PARA PRODUÇÃO", "success")
    if latest_run.accuracy_pct >= 75.0:
        return ("ATENÇÃO — Requer Curadoria Adicional", "warning")
    return ("NÃO PRONTO — Assertividade Abaixo da Meta", "danger")


def generate_docs(
    bundle: SpaceBundle,
    output_dir: Path | None = None,
    templates_dir: Path | None = None,
    lint_report: LintReport | None = None,
    history: HistoryStore | None = None,
) -> dict[str, Path]:
    """
    Gera automaticamente a suíte de documentação do Genie Space:
    1. SPEC_TECNICA.md
    2. RELATORIO_EXECUTIVO.md
    3. relatorio_executivo.html
    4. GUIA_USUARIO.md
    """
    tpl_dir = templates_dir or _default_templates_dir()
    env = Environment(
        loader=FileSystemLoader(str(tpl_dir)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    out_dir = output_dir or (
        (bundle.root_dir / "docs") if bundle.root_dir else (Path.cwd() / "docs" / bundle.space.name)
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    l_report = lint_report or lint_space(bundle)
    latest_run: BenchmarkRunRecord | None = None
    recent_runs: list[BenchmarkRunRecord] = []
    regression: RegressionDiff | None = None

    if history is not None:
        recent_runs = history.list_runs(bundle.space.name, limit=10)
        latest_run = history.get_latest_run(bundle.space.name)
        if latest_run is not None:
            prev = history.get_previous_run(bundle.space.name, latest_run.run_id)
            if prev is not None:
                regression = history.compare_runs(prev, latest_run)

    readiness_label, readiness_class = _production_readiness_status(l_report, latest_run)

    # Agrupa termos/sinônimos amigáveis para o Guia do Usuário
    glossary: list[dict[str, str]] = []
    for src in bundle.sources.tables + bundle.sources.metric_views:
        short_name = src.identifier.split(".")[-1]
        for col in src.column_configs:
            if col.exclude:
                continue
            if col.synonyms or col.description:
                glossary.append(
                    {
                        "source": short_name,
                        "column": col.column_name,
                        "synonyms": ", ".join(col.synonyms) if col.synonyms else "—",
                        "description": " ".join(col.description) if col.description else "—",
                    }
                )

    context: dict[str, Any] = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "bundle": bundle,
        "space": bundle.space,
        "sources": bundle.sources,
        "instructions": bundle.instructions,
        "benchmarks": bundle.benchmarks,
        "lint": l_report,
        "latest_run": latest_run,
        "recent_runs": recent_runs,
        "regression": regression,
        "readiness_label": readiness_label,
        "readiness_class": readiness_class,
        "glossary": glossary,
    }

    outputs: dict[str, Path] = {}
    targets = [
        ("spec_tecnica", "spec_tecnica.md.j2", "SPEC_TECNICA.md"),
        ("relatorio_executivo_md", "relatorio_executivo.md.j2", "RELATORIO_EXECUTIVO.md"),
        ("relatorio_executivo_html", "relatorio_executivo.html.j2", "relatorio_executivo.html"),
        ("guia_usuario", "guia_usuario.md.j2", "GUIA_USUARIO.md"),
    ]
    for key, tpl_name, filename in targets:
        rendered = env.get_template(tpl_name).render(**context)
        dest = out_dir / filename
        dest.write_text(rendered, encoding="utf-8")
        outputs[key] = dest

    return outputs
