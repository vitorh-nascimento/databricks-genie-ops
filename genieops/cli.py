"""CLI modular do Databricks GenieOps (Typer + Rich)."""

from __future__ import annotations

import json
import webbrowser
from pathlib import Path
from typing import Literal

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from genieops import __version__
from genieops.agent_mode import AgentModeClient, ExecutionMode
from genieops.benchmark import BenchmarkMode, run_benchmark
from genieops.compiler import compile_space, parse_serialized_space
from genieops.databricks_client import DatabricksClient
from genieops.deployer import compute_remote_diff, deploy_space
from genieops.diagnoser import FIX_LEVER_HIERARCHY, diagnose_run
from genieops.docs_generator import generate_docs
from genieops.harvester import harvest_feedback
from genieops.history import HistoryStore
from genieops.judges import JudgeProviderName, create_judge
from genieops.linter import lint_space
from genieops.loader import (
    init_space_scaffold,
    list_spaces,
    load_space,
    resolve_env_config,
    save_space,
)
from genieops.migrator import remap_space_bundle
from genieops.profiler import profile_space
from genieops.uc_export import build_uc_export_plan, execute_uc_export_plan

app = typer.Typer(
    name="genieops",
    help="Databricks GenieOps — Framework Genie-as-Code para curadoria, auditoria, benchmark e deploy.",
    no_args_is_help=True,
)
console = Console()


def _build_client(profile: str | None, warehouse_id: str | None) -> DatabricksClient:
    clean_wh = None if (warehouse_id and warehouse_id.startswith("<")) else warehouse_id
    return DatabricksClient(profile=profile, warehouse_id=clean_wh)


@app.command("version")
def cmd_version() -> None:
    """Exibe a versão instalada do GenieOps."""
    console.print(f"[bold cyan]databricks-genie-ops[/bold cyan] v{__version__}")


@app.command("list")
def cmd_list() -> None:
    """Lista todos os Genie Spaces declarados em spaces/."""
    names = list_spaces()
    if not names:
        console.print("[yellow]Nenhum Genie Space encontrado em spaces/. Use `genieops init <nome>`.[/yellow]")
        return

    table = Table(title="Genie Spaces Registrados (Genie-as-Code)")
    table.add_column("Space", style="bold cyan")
    table.add_column("Título")
    table.add_column("Fontes", justify="right")
    table.add_column("Benchmarks", justify="right")
    table.add_column("Ambientes")

    for name in names:
        b = load_space(name)
        src_count = len(b.sources.tables) + len(b.sources.metric_views) + len(b.sources.volumes)
        envs = ", ".join(sorted(b.space.environments.keys())) or b.space.default_env
        table.add_row(name, b.space.title, str(src_count), str(len(b.benchmarks.questions)), envs)

    console.print(table)


@app.command("init")
def cmd_init(
    name: str = typer.Argument(..., help="Nome técnico do Genie Space (ex.: vendas_comercial)."),
    title: str | None = typer.Option(None, "--title", "-t", help="Título amigável do Genie Space."),
    catalog: str = typer.Option("analytics_dev", "--catalog", help="Catalog inicial no Unity Catalog."),
    schema: str = typer.Option("domain_gold", "--schema", help="Schema inicial no Unity Catalog."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Sobrescrever se já existir."),
) -> None:
    """Cria o scaffold declarativo completo de um novo Genie Space em spaces/<nome>/."""
    try:
        dest = init_space_scaffold(name, title=title, catalog=catalog, schema=schema, overwrite=overwrite)
    except FileExistsError as exc:
        console.print(f"[red]Erro:[/red] {exc}")
        raise typer.Exit(code=1)

    console.print(
        Panel.fit(
            f"[green]Scaffold criado com sucesso![/green]\n"
            f"Diretório: [bold]{dest}[/bold]\n\n"
            f"Próximos passos recomendados:\n"
            f"  1. Edite sources.yaml, instructions.yaml e benchmarks.yaml\n"
            f"  2. Execute: [cyan]genieops lint {name}[/cyan]\n"
            f"  3. Execute: [cyan]genieops benchmark {name} --env dev --mode offline[/cyan]",
            title="GenieOps Init",
        )
    )


@app.command("pull")
def cmd_pull(
    space_id: str = typer.Argument(..., help="ID do Genie Space existente no Databricks."),
    profile: str = typer.Option(..., "--profile", "-p", help="Perfil do Databricks CLI."),
    name: str | None = typer.Option(None, "--name", "-n", help="Nome da pasta local em spaces/."),
    env: str = typer.Option("dev", "--env", "-e", help="Ambiente a registrar em space.yaml."),
) -> None:
    """Importa um Genie Space existente do Databricks e converte para YAML declarativo."""
    client = _build_client(profile=profile, warehouse_id=None)
    remote = client.get_space(space_id, include_serialized_space=True)
    inferred_name = name or (
        str(remote.get("title") or space_id).lower().replace(" ", "_").replace("-", "_")
    )
    bundle = parse_serialized_space(remote, space_name=inferred_name, env_name=env, profile=profile)
    saved_dir = save_space(bundle)
    console.print(
        f"[green]Genie Space '{space_id}' importado com sucesso para[/green] [bold]{saved_dir}[/bold]"
    )


@app.command("compile")
def cmd_compile(
    name: str = typer.Argument(..., help="Nome do Genie Space em spaces/."),
    env: str | None = typer.Option(None, "--env", "-e", help="Ambiente alvo para remapeamento."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Arquivo JSON de saída."),
) -> None:
    """Compila o Genie Space para o JSON determinístico oficial `serialized_space` v2."""
    bundle = load_space(name)
    if env and env != bundle.space.default_env:
        src_cfg = resolve_env_config(bundle, bundle.space.default_env)
        dst_cfg = resolve_env_config(bundle, env)
        bundle, _ = remap_space_bundle(bundle, src_cfg, dst_cfg)

    payload = compile_space(bundle)
    formatted = json.dumps(payload, indent=2, ensure_ascii=False)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(formatted, encoding="utf-8")
        console.print(f"[green]Payload v2 salvo em[/green] [bold]{output}[/bold]")
    else:
        console.print(formatted)


@app.command("diff")
def cmd_diff(
    name: str = typer.Argument(..., help="Nome do Genie Space em spaces/."),
    env: str = typer.Option("dev", "--env", "-e", help="Ambiente alvo."),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Sobrescrever perfil CLI."),
) -> None:
    """Compara o estado local compilado com o Genie Space remoto antes do deploy."""
    bundle = load_space(name)
    env_cfg = resolve_env_config(bundle, env)
    client = _build_client(profile=profile or env_cfg.profile, warehouse_id=env_cfg.warehouse_id)

    diff, space_id = compute_remote_diff(bundle, env_name=env, client=client)
    console.print(f"[bold]Diff de '{name}' ({env})[/bold] — Space remoto: {space_id or 'NOVO'}")
    for line in diff.summary:
        console.print(f"  {line}")
    if diff.unified_diff:
        console.print("\n" + diff.unified_diff)


@app.command("deploy")
def cmd_deploy(
    name: str = typer.Argument(..., help="Nome do Genie Space em spaces/."),
    env: str = typer.Option("dev", "--env", "-e", help="Ambiente alvo (dev, qa, prod)."),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Sobrescrever perfil CLI."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Apenas valida e gera payload sem chamar API."),
    skip_lint: bool = typer.Option(False, "--skip-lint", help="Ignorar bloqueio de erros do linter."),
    persist_id: bool = typer.Option(False, "--persist-id", help="Salvar space_id criado em space.yaml."),
) -> None:
    """Valida, compila e publica o Genie Space no Databricks com backup automático da versão anterior."""
    bundle = load_space(name)
    env_cfg = resolve_env_config(bundle, env)
    client = _build_client(profile=profile or env_cfg.profile, warehouse_id=env_cfg.warehouse_id)

    res = deploy_space(
        bundle,
        env_name=env,
        client=client,
        dry_run=dry_run,
        skip_lint=skip_lint,
        persist_space_id=persist_id,
    )

    if res.action == "BLOCKED_BY_LINT":
        console.print(f"[red]{res.message}[/red]")
        if res.lint_report:
            for issue in res.lint_report.issues:
                if issue.severity == "ERROR":
                    console.print(f"  [red][{issue.code}][/red] {issue.surface}: {issue.message}")
        raise typer.Exit(code=1)

    console.print(f"[green][{res.action}][/green] {res.message}")
    if res.backup_path:
        console.print(f"  Backup para rollback salvo em: [cyan]{res.backup_path}[/cyan]")
    if res.payload_path:
        console.print(f"  Payload compilado: [cyan]{res.payload_path}[/cyan]")


@app.command("migrate")
def cmd_migrate(
    name: str = typer.Argument(..., help="Nome do Genie Space em spaces/."),
    from_env: str = typer.Option("dev", "--from", help="Ambiente de origem."),
    to_env: str = typer.Option("prod", "--to", help="Ambiente de destino."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Salvar payload migrado em JSON."),
    deploy: bool = typer.Option(False, "--deploy", help="Executar deploy imediato no ambiente de destino."),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Perfil CLI do destino."),
) -> None:
    """Promove um Genie Space entre ambientes remapeando catalog, schema e /Volumes/... em todas as superfícies."""
    bundle = load_space(name)
    src_cfg = resolve_env_config(bundle, from_env)
    dst_cfg = resolve_env_config(bundle, to_env)

    remapped, report = remap_space_bundle(bundle, src_cfg, dst_cfg)
    payload = compile_space(remapped)

    console.print(
        Panel.fit(
            f"Origem: [bold]{from_env}[/bold] ({src_cfg.catalog}.{src_cfg.schema_name})\n"
            f"Destino: [bold]{to_env}[/bold] ({dst_cfg.catalog}.{dst_cfg.schema_name})\n"
            f"Superfícies remapeadas: {report.surfaces_touched or 'nenhuma alteração textual necessária'}",
            title=f"GenieOps Migrate — {name}",
        )
    )

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        console.print(f"[green]Payload migrado salvo em[/green] [bold]{output}[/bold]")

    if deploy:
        client = _build_client(profile=profile or dst_cfg.profile, warehouse_id=dst_cfg.warehouse_id)
        res = deploy_space(remapped, env_name=to_env, client=client)
        if res.action == "BLOCKED_BY_LINT":
            console.print(f"[red]{res.message}[/red]")
            raise typer.Exit(code=1)
        console.print(f"[green][{res.action}][/green] {res.message}")


@app.command("lint")
def cmd_lint(
    name: str = typer.Argument(..., help="Nome do Genie Space em spaces/."),
    validate_sql: bool = typer.Option(False, "--validate-sql", help="Executar EXPLAIN read-only no SQL Warehouse."),
    env: str = typer.Option("dev", "--env", "-e", help="Ambiente para validação SQL."),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Sobrescrever perfil CLI."),
    strict: bool = typer.Option(False, "--strict", help="Retornar exit code 1 se houver qualquer ERROR."),
) -> None:
    """Executa o Genie Health Check (regras estáticas + EXPLAIN SQL opcional)."""
    bundle = load_space(name)
    client = None
    warehouse_id = None
    if validate_sql:
        env_cfg = resolve_env_config(bundle, env)
        warehouse_id = env_cfg.warehouse_id
        client = _build_client(profile=profile or env_cfg.profile, warehouse_id=warehouse_id)

    report = lint_space(bundle, validate_sql=validate_sql, client=client, warehouse_id=warehouse_id)

    color = "green" if report.health_score >= 85 else ("yellow" if report.health_score >= 65 else "red")
    console.print(
        Panel.fit(
            f"Space: [bold]{name}[/bold]\n"
            f"Health Score: [{color}][bold]{report.health_score}/100[/bold][/{color}]\n"
            f"Erros: [red]{report.error_count}[/red] | Avisos: [yellow]{report.warning_count}[/yellow] | Infos: [cyan]{report.info_count}[/cyan]",
            title="Genie Health Check (Linter)",
        )
    )

    if report.issues:
        tbl = Table(show_lines=True)
        tbl.add_column("Sev.", width=9)
        tbl.add_column("Código", width=8)
        tbl.add_column("Superfície", width=32)
        tbl.add_column("Achado & Recomendação")
        for issue in report.issues:
            sev_style = {"ERROR": "bold red", "WARNING": "yellow", "INFO": "cyan"}[issue.severity]
            detail = issue.message + (f"\n[dim]→ {issue.recommendation}[/dim]" if issue.recommendation else "")
            tbl.add_row(f"[{sev_style}]{issue.severity}[/{sev_style}]", issue.code, issue.surface, detail)
        console.print(tbl)
    else:
        console.print("[green]Nenhum problema encontrado! Curadoria em conformidade total.[/green]")

    if strict and not report.passed:
        raise typer.Exit(code=1)


@app.command("profile")
def cmd_profile(
    name: str = typer.Argument(..., help="Nome do Genie Space em spaces/."),
    env: str = typer.Option("dev", "--env", "-e", help="Ambiente alvo para profiling read-only."),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Sobrescrever perfil CLI."),
    query_history: bool = typer.Option(False, "--query-history", help="Consultar system.query.history (read-only)."),
) -> None:
    """Executa Data Profiling read-only e gera sugestões de curadoria (entity_matching, exclude, joins)."""
    bundle = load_space(name)
    env_cfg = resolve_env_config(bundle, env)
    client = _build_client(profile=profile or env_cfg.profile, warehouse_id=env_cfg.warehouse_id)

    rep = profile_space(
        bundle,
        client=client,
        env_name=env,
        warehouse_id=env_cfg.warehouse_id,
        include_query_history=query_history,
    )

    console.print(f"[bold]Profiling concluído:[/bold] {rep.tables_profiled} fonte(s) analisada(s), {len(rep.suggestions)} sugestão(ões).")
    if rep.ast_profile is not None:
        ap = rep.ast_profile
        console.print(
            f"[cyan]AST Query History:[/cyan] {ap.queries_parsed} query(ies) parseadas "
            f"(joins={len(ap.join_patterns)}, filtros={len(ap.filter_patterns)}, agregações={len(ap.aggregation_patterns)})."
        )
    for w in rep.warnings:
        console.print(f"[yellow]Aviso:[/yellow] {w}")

    if rep.suggestions:
        tbl = Table(title="Sugestões de Auto-Curadoria", show_lines=True)
        tbl.add_column("Categoria", style="bold cyan")
        tbl.add_column("Tabela / Coluna")
        tbl.add_column("Justificativa")
        tbl.add_column("Trecho YAML Sugerido")
        for s in rep.suggestions:
            tbl.add_row(s.category, f"{s.table}\n{s.column or ''}", s.reason, s.suggested_yaml)
        console.print(tbl)


@app.command("benchmark")
def cmd_benchmark(
    name: str = typer.Argument(..., help="Nome do Genie Space em spaces/."),
    env: str = typer.Option("dev", "--env", "-e", help="Ambiente alvo."),
    mode: BenchmarkMode = typer.Option("offline", "--mode", "-m", help="Modo: offline | live | eval-run | agent."),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Sobrescrever perfil CLI."),
    ids: str | None = typer.Option(None, "--ids", help="Lista separada por vírgula de case IDs (staged gate)."),
    only_failed: bool = typer.Option(False, "--only-failed", help="Reexecutar apenas falhas da última rodada."),
    rel_tol: float = typer.Option(1e-4, "--rel-tol", help="Tolerância numérica relativa na comparação de Result Sets."),
    abs_tol: float = typer.Option(1e-2, "--abs-tol", help="Tolerância numérica absoluta na comparação de Result Sets."),
    execution_mode: ExecutionMode = typer.Option("STANDARD", "--execution-mode", help="Modo Agent Mode: STANDARD | FLASH."),
    judge: JudgeProviderName = typer.Option("heuristic", "--judge", help="Provedor LLM-as-a-Judge: heuristic | databricks | openai."),
    judge_endpoint: str | None = typer.Option(None, "--judge-endpoint", help="Endpoint FMAPI ou modelo do juiz."),
) -> None:
    """Executa a suíte de benchmark (offline, live, eval-run ou agent SSE) e registra histórico/regressão em SQLite."""
    bundle = load_space(name)
    env_cfg = resolve_env_config(bundle, env)
    history = HistoryStore()
    eff_profile = profile or env_cfg.profile

    client = None
    agent_client = None
    judge_provider = None

    if mode in ("live", "eval-run"):
        client = _build_client(profile=eff_profile, warehouse_id=env_cfg.warehouse_id)
    if mode in ("live", "agent"):
        judge_provider = create_judge(judge, profile=eff_profile, endpoint=judge_endpoint)
    if mode == "agent":
        agent_client = AgentModeClient(profile=eff_profile)

    id_list = [i.strip() for i in ids.split(",")] if ids else None
    record, diff = run_benchmark(
        bundle,
        env_name=env,
        mode=mode,
        client=client,
        space_id=env_cfg.space_id,
        warehouse_id=env_cfg.warehouse_id,
        history=history,
        ids=id_list,
        only_failed=only_failed,
        rel_tol=rel_tol,
        abs_tol=abs_tol,
        judge_provider=judge_provider,
        agent_client=agent_client,
        execution_mode=execution_mode,
    )

    console.print(
        Panel.fit(
            f"Run ID: [bold]{record.run_id}[/bold] | Modo: [cyan]{record.mode}[/cyan] | Env: [cyan]{record.env}[/cyan]\n"
            f"Assertividade: [bold green]{record.accuracy_pct:.1f}%[/bold green] "
            f"(PASS={record.passed}, FAIL={record.failed}, REVIEW={record.needs_review})\n"
            f"Latência — Média: {record.avg_latency_ms:.1f}ms | P50: {record.p50_latency_ms:.1f}ms | P95: {record.p95_latency_ms:.1f}ms",
            title=f"Benchmark — {name}",
        )
    )

    if diff is not None:
        console.print(
            f"[bold]Comparação vs rodada anterior ({diff.previous_run_id}):[/bold] "
            f"{diff.previous_accuracy:.1f}% -> {diff.current_accuracy:.1f}% (delta={diff.delta_accuracy:+.2f}pp) | "
            f"fixed={len(diff.fixed)}, regressed={len(diff.regressed)}, unchanged={len(diff.unchanged)}"
        )

    if record.failed > 0:
        tbl = Table(title="Casos com Falha")
        tbl.add_column("ID")
        tbl.add_column("Pergunta")
        tbl.add_column("Motivo")
        for it in record.items:
            if it.status == "BAD":
                tbl.add_row(it.case_id, it.question[:60], it.error_message or "")
        console.print(tbl)


@app.command("diagnose")
def cmd_diagnose(
    name: str = typer.Argument(..., help="Nome do Genie Space em spaces/."),
    run_id: str | None = typer.Option(None, "--run-id", help="ID da execução no history.db (padrão: última)."),
) -> None:
    """Classifica causa raiz das falhas e propõe plano de correção seguindo a hierarquia oficial Databricks."""
    bundle = load_space(name)
    history = HistoryStore()
    run = history.get_run(run_id) if run_id else history.get_latest_run(name)
    if run is None:
        console.print(f"[yellow]Nenhuma rodada de benchmark encontrada para '{name}'. Execute `genieops benchmark` primeiro.[/yellow]")
        raise typer.Exit(code=1)

    report = diagnose_run(run, bundle)
    if report.total_failures == 0:
        console.print(f"[green]Nenhuma falha (status=BAD) encontrada na rodada {run.run_id}![/green]")
        return

    console.print(f"[bold]Diagnóstico da rodada {run.run_id} — {report.total_failures} falha(s):[/bold]")
    tbl = Table(show_lines=True)
    tbl.add_column("Case ID", style="bold")
    tbl.add_column("Causa Raiz", style="bold red")
    tbl.add_column("Alavanca Recomendada", style="green")
    tbl.add_column("Plano Proposto (Revisão Manual Obrigatória)")

    for d in report.diagnoses:
        tbl.add_row(
            d.case_id,
            f"{d.root_cause_class}\n[dim](confiança: {d.confidence})[/dim]",
            d.recommended_lever,
            f"{d.proposed_action}\n[dim]Evitar: {d.avoid_antipattern}[/dim]",
        )
    console.print(tbl)
    console.print("\n[dim]Hierarquia oficial de correção (menor superfície estruturada primeiro):[/dim]")
    for step in FIX_LEVER_HIERARCHY:
        console.print(f"  [dim]{step}[/dim]")


@app.command("harvest-feedback")
def cmd_harvest_feedback(
    name: str = typer.Argument(..., help="Nome do Genie Space em spaces/."),
    env: str = typer.Option("prod", "--env", "-e", help="Ambiente de onde coletar conversas/feedbacks."),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Sobrescrever perfil CLI."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Arquivo YAML de rascunho."),
    include_audit: bool = typer.Option(False, "--include-audit", help="Incluir eventos de feedback em system.access.audit (read-only)."),
    days: int = typer.Option(30, "--days", help="Janela em dias para consulta em system.access.audit."),
    dedup_threshold: float = typer.Option(0.78, "--dedup-threshold", help="Limiar de similaridade semântica (0..1) para deduplicação."),
) -> None:
    """Coleta perguntas com falha/feedback negativo (API + audit log), deduplica semanticamente e gera rascunho YAML."""
    bundle = load_space(name)
    env_cfg = resolve_env_config(bundle, env)
    if not env_cfg.space_id:
        console.print(f"[red]Erro:[/red] space_id não configurado para o ambiente '{env}'.")
        raise typer.Exit(code=1)

    client = _build_client(profile=profile or env_cfg.profile, warehouse_id=env_cfg.warehouse_id)
    dest = output or (Path("spaces") / name / "benchmarks_draft.yaml")
    existing_qs = [b.question for b in bundle.benchmarks.questions]
    rep = harvest_feedback(
        name,
        space_id=env_cfg.space_id,
        client=client,
        output_path=dest,
        include_audit=include_audit,
        audit_days=days,
        warehouse_id=env_cfg.warehouse_id,
        existing_questions=existing_qs,
        similarity_threshold=dedup_threshold,
    )
    console.print(
        f"[green]Coleta concluída:[/green] {rep.conversations_scanned} conversa(s), "
        f"{rep.audit_events_scanned} evento(s) audit, {rep.duplicates_merged} duplicata(s) agrupada(s), "
        f"{len(rep.candidates)} candidato(s) salvo(s) em [bold]{rep.draft_path}[/bold]."
    )
    for w in rep.warnings:
        console.print(f"[yellow]Aviso:[/yellow] {w}")


@app.command("export-delta")
def cmd_export_delta(
    name: str = typer.Argument(..., help="Nome do Genie Space em spaces/."),
    catalog: str = typer.Option(..., "--catalog", help="Catalog de destino no Unity Catalog."),
    schema: str = typer.Option(..., "--schema", help="Schema de destino no Unity Catalog."),
    schema_mode: Literal["four_tables", "events"] = typer.Option(
        "four_tables", "--schema-mode", help="Schema oficial Databricks: four_tables | events."
    ),
    env: str = typer.Option("dev", "--env", "-e", help="Ambiente para resolução de perfil/warehouse."),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Sobrescrever perfil CLI."),
    output_sql: Path | None = typer.Option(None, "--output-sql", "-o", help="Salvar script SQL DDL+MERGE."),
    execute: bool = typer.Option(False, "--execute", help="Executar DDL+MERGE no SQL Warehouse (opt-in explícito)."),
    limit: int = typer.Option(50, "--limit", help="Máximo de rodadas históricas a exportar."),
) -> None:
    """Exporta o histórico SQLite (history.db) para tabelas Delta oficiais (`genie_opt_*`) no Unity Catalog."""
    bundle = load_space(name)
    env_cfg = resolve_env_config(bundle, env)
    history = HistoryStore()
    dest_sql = output_sql or (Path(".genieops") / "staging" / f"{name}_uc_export_{schema_mode}.sql")

    plan = build_uc_export_plan(
        bundle,
        history,
        catalog=catalog,
        schema=schema,
        schema_mode=schema_mode,
        space_id=env_cfg.space_id,
        limit=limit,
        output_sql_path=dest_sql,
    )
    console.print(
        Panel.fit(
            f"Space: [bold]{name}[/bold] | Destino: [cyan]{plan.catalog}.{plan.schema}[/cyan]\n"
            f"Schema: [bold]{plan.schema_mode}[/bold] | Rodadas: {plan.runs_exported} | "
            f"DDLs: {len(plan.ddl_statements)} | MERGEs: {len(plan.dml_statements)}\n"
            f"Arquivo SQL gerado: [cyan]{plan.output_sql_path}[/cyan]",
            title="GenieOps Export Delta (Unity Catalog)",
        )
    )

    if execute:
        client = _build_client(profile=profile or env_cfg.profile, warehouse_id=env_cfg.warehouse_id)
        execute_uc_export_plan(plan, client=client, warehouse_id=env_cfg.warehouse_id)
        console.print("[green]Exportação Delta executada com sucesso no Unity Catalog![/green]")
    else:
        console.print("[dim]Modo dry-run seguro. Passe `--execute` para aplicar no SQL Warehouse.[/dim]")


@app.command("serve")
def cmd_serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Host de bind local."),
    port: int = typer.Option(8765, "--port", help="Porta HTTP do Painel Web Local."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Não abrir navegador automaticamente."),
) -> None:
    """Inicia o Painel Web Local (FastAPI + React/Vite/Tailwind) para observabilidade dos Genie Spaces."""
    import uvicorn

    from genieops.web_api import create_app

    url = f"http://{host}:{port}"
    friendly_url = f"http://genieops.localhost:{port}" if host in ("127.0.0.1", "localhost") else url
    console.print(
        Panel.fit(
            f"Painel Web Databricks GenieOps rodando em [bold cyan]{friendly_url}[/bold cyan] (ou {url})\n"
            f"API OpenAPI Docs: [cyan]{friendly_url}/docs[/cyan]\n"
            f"Pressione Ctrl+C para encerrar.",
            title="GenieOps Dashboard (Fase 2)",
        )
    )
    if not no_browser:
        webbrowser.open(friendly_url)
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


@app.command("docs")
def cmd_docs(
    name: str = typer.Argument(..., help="Nome do Genie Space em spaces/."),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o", help="Diretório de saída dos artefatos."),
) -> None:
    """Gera SPEC_TECNICA.md, RELATORIO_EXECUTIVO.md/.html e GUIA_USUARIO.md automaticamente."""
    bundle = load_space(name)
    history = HistoryStore()
    outputs = generate_docs(bundle, output_dir=output_dir, history=history)
    console.print(f"[green]Documentação gerada com sucesso para '{name}':[/green]")
    for key, path in outputs.items():
        console.print(f"  • {key}: [cyan]{path}[/cyan]")


if __name__ == "__main__":
    app()
