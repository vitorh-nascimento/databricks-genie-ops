"""Exportação do histórico local (history.db) para tabelas Delta no Unity Catalog (schema oficial Databricks)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from genieops.compiler import compile_space, payload_hash
from genieops.databricks_client import DatabricksClient
from genieops.diagnoser import diagnose_run
from genieops.history import BenchmarkRunRecord, HistoryStore
from genieops.models import SpaceBundle

UCExportSchemaMode = Literal["four_tables", "events"]

UC_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
ALLOWED_UC_OPT_TABLES = frozenset(
    {
        "genie_opt_runs",
        "genie_opt_config_versions",
        "genie_opt_eval_results",
        "genie_opt_repair_analysis",
        "genie_opt_events",
    }
)


@dataclass
class UCExportPlan:
    """Plano completo de DDL + DML para persistência de histórico de otimização no Unity Catalog."""

    space_name: str
    catalog: str
    schema: str
    schema_mode: UCExportSchemaMode
    runs_exported: int
    ddl_statements: list[str] = field(default_factory=list)
    dml_statements: list[str] = field(default_factory=list)
    output_sql_path: Path | None = None
    executed: bool = False

    def full_sql(self) -> str:
        header = (
            f"-- Databricks GenieOps — Exportação Delta Unity Catalog ({self.schema_mode})\n"
            f"-- Space: {self.space_name} | Destino: {quote_ident(self.catalog)}.{quote_ident(self.schema)}\n"
            f"-- Rodadas incluídas: {self.runs_exported}\n\n"
        )
        stmts = self.ddl_statements + self.dml_statements
        return header + "\n\n".join(s.rstrip(";") + ";" for s in stmts) + "\n"


def validate_uc_identifier(name: str, label: str = "identificador") -> str:
    cleaned = name.strip().strip("`")
    if not cleaned or not UC_IDENT_RE.match(cleaned):
        raise ValueError(
            f"Nome inválido para {label} no Unity Catalog: '{name}'. "
            "Use apenas letras, números, '_' ou '-'."
        )
    return cleaned


def quote_ident(name: str) -> str:
    clean = validate_uc_identifier(name)
    return f"`{clean}`" if "-" in clean else clean


def sql_str(value: str | None) -> str:
    if value is None:
        return "NULL"
    escaped = value.replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"


def _sha256_short(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def assert_uc_export_sql_safe(sql: str, catalog: str, schema: str) -> None:
    """
    Guarda dedicada para exportação UC: permite EXCLUSIVAMENTE CREATE TABLE IF NOT EXISTS,
    MERGE INTO ou INSERT INTO sobre as tabelas `genie_opt_*` dentro de `<catalog>.<schema>`.
    Nunca permite DROP, TRUNCATE, DELETE ou escrita em tabelas de negócio.
    """
    cleaned = sql.strip()
    upper = re.sub(r"\s+", " ", cleaned).upper()

    for forbidden in ("DROP ", "TRUNCATE ", "DELETE ", "ALTER ", "GRANT ", "REVOKE "):
        if forbidden in upper:
            raise ValueError(f"Comando proibido em exportação UC Delta: {forbidden.strip()}")

    cat_q = quote_ident(catalog)
    sch_q = quote_ident(schema)
    allowed_prefixes = tuple(
        f"{cat_q}.{sch_q}.{tbl}".upper() for tbl in ALLOWED_UC_OPT_TABLES
    )

    m = re.match(
        r"^(?:CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS|MERGE\s+INTO|INSERT\s+INTO)\s+([^\s(]+)",
        upper,
    )
    if not m:
        raise ValueError(f"Instrução SQL não permitida no export UC: {cleaned[:80]}")

    target = m.group(1).strip()
    if target not in allowed_prefixes:
        raise ValueError(
            f"Tabela de destino '{target}' fora da allowlist oficial `genie_opt_*` em {cat_q}.{sch_q}."
        )


def generate_uc_ddl(catalog: str, schema: str, schema_mode: UCExportSchemaMode = "four_tables") -> list[str]:
    """Gera o DDL oficial Databricks (`uc-persistence.md`) para tabelas Delta de histórico."""
    prefix = f"{quote_ident(catalog)}.{quote_ident(schema)}"

    if schema_mode == "events":
        return [
            f"""CREATE TABLE IF NOT EXISTS {prefix}.genie_opt_events (
  event_id            STRING NOT NULL,
  event_ts            TIMESTAMP NOT NULL,
  event_type          STRING NOT NULL,
  session_id          STRING,
  run_id              STRING,
  space_id            STRING,
  config_version_id   STRING,
  eval_run_id         STRING,
  question_id         STRING,
  payload_json        STRING
) USING DELTA"""
        ]

    return [
        f"""CREATE TABLE IF NOT EXISTS {prefix}.genie_opt_runs (
  run_id                      STRING NOT NULL,
  session_id                  STRING,
  space_id                    STRING NOT NULL,
  space_name                  STRING,
  benchmark_execution_target  STRING,
  benchmark_id                STRING,
  benchmark_version_or_hash   STRING,
  iteration                   INT,
  parent_run_id               STRING,
  baseline_config_version_id  STRING,
  candidate_config_version_id STRING,
  target_cluster              STRING,
  repair_lever                STRING,
  status                      STRING,
  started_at                  TIMESTAMP,
  ended_at                    TIMESTAMP,
  baseline_score              DOUBLE,
  candidate_score             DOUBLE,
  score_delta                 DOUBLE,
  fixed_count                 INT,
  regressed_count             INT,
  unchanged_bad_count         INT,
  unchanged_good_count        INT,
  excluded_count              INT,
  decision                    STRING,
  notes                       STRING
) USING DELTA""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}.genie_opt_config_versions (
  config_version_id        STRING NOT NULL,
  run_id                   STRING NOT NULL,
  space_id                 STRING NOT NULL,
  version_label            STRING,
  parent_config_version_id STRING,
  captured_at              TIMESTAMP,
  captured_by              STRING,
  config_hash              STRING,
  config_json              STRING,
  changed_surfaces         STRING,
  change_summary           STRING
) USING DELTA""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}.genie_opt_eval_results (
  eval_result_id            STRING NOT NULL,
  eval_run_id               STRING NOT NULL,
  run_id                    STRING NOT NULL,
  space_id                  STRING NOT NULL,
  benchmark_id              STRING,
  benchmark_version_or_hash STRING,
  eval_type                 STRING,
  evaluated_at              TIMESTAMP,
  question_id               STRING,
  question_text             STRING,
  benchmark_field_strategy  STRING,
  assessment                STRING,
  valid_tuning_failure      BOOLEAN,
  exclusion_reason          STRING,
  primary_failure           STRING,
  secondary_signal          STRING,
  failure_cluster           STRING,
  expected_sql_hash         STRING,
  generated_sql_hash        STRING,
  generated_sql             STRING,
  evaluation_note_hash      STRING,
  expected_result_digest    STRING,
  actual_result_digest      STRING,
  judge_notes               STRING,
  latency_ms                BIGINT,
  error_message             STRING
) USING DELTA""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}.genie_opt_repair_analysis (
  analysis_id             STRING NOT NULL,
  run_id                  STRING NOT NULL,
  space_id                STRING NOT NULL,
  created_at              TIMESTAMP,
  cluster_id              STRING,
  affected_question_ids   STRING,
  root_cause              STRING,
  evidence_summary        STRING,
  selected_lever          STRING,
  rejected_levers         STRING,
  config_surface          STRING,
  planned_patch_summary   STRING,
  expected_fix_count      INT,
  regression_risk         STRING,
  benchmark_leakage_check STRING,
  acceptance_decision     STRING,
  reflection              STRING,
  next_hypothesis         STRING
) USING DELTA""",
    ]


def build_uc_export_plan(
    bundle: SpaceBundle,
    history: HistoryStore,
    catalog: str,
    schema: str,
    *,
    schema_mode: UCExportSchemaMode = "four_tables",
    space_id: str | None = None,
    limit: int = 50,
    output_sql_path: Path | None = None,
) -> UCExportPlan:
    """Constrói o plano completo (DDL + MERGE idempotente) a partir do history.db local."""
    cat_clean = validate_uc_identifier(catalog, "catalog")
    sch_clean = validate_uc_identifier(schema, "schema")
    prefix = f"{quote_ident(cat_clean)}.{quote_ident(sch_clean)}"

    summaries = history.list_runs(bundle.space.name, limit=limit)
    full_runs: list[BenchmarkRunRecord] = []
    for s in reversed(summaries):  # ordem cronológica crescente
        rec = history.get_run(s.run_id)
        if rec is not None:
            full_runs.append(rec)

    compiled = compile_space(bundle)
    compiled_json = json.dumps(compiled, separators=(",", ":"), ensure_ascii=False)
    current_cfg_hash = payload_hash(compiled)
    resolved_space_id = space_id or f"local:{bundle.space.name}"

    ddl = generate_uc_ddl(cat_clean, sch_clean, schema_mode=schema_mode)
    dml: list[str] = []

    if schema_mode == "events":
        for run in full_runs:
            ev_id = f"ev_{run.run_id}"
            payload = {
                "run_id": run.run_id,
                "space_name": run.space_name,
                "env": run.env,
                "mode": run.mode,
                "accuracy_pct": run.accuracy_pct,
                "passed": run.passed,
                "failed": run.failed,
                "needs_review": run.needs_review,
                "p50_latency_ms": run.p50_latency_ms,
                "p95_latency_ms": run.p95_latency_ms,
                "config_hash": run.config_hash,
            }
            dml.append(
                f"MERGE INTO {prefix}.genie_opt_events AS t\n"
                f"USING (SELECT {sql_str(ev_id)} AS event_id) AS s\n"
                f"ON t.event_id = s.event_id\n"
                f"WHEN NOT MATCHED THEN INSERT (\n"
                f"  event_id, event_ts, event_type, session_id, run_id, space_id,\n"
                f"  config_version_id, eval_run_id, question_id, payload_json\n"
                f") VALUES (\n"
                f"  {sql_str(ev_id)}, TIMESTAMP {sql_str(run.created_at)}, 'eval_run_completed',\n"
                f"  {sql_str(run.env)}, {sql_str(run.run_id)}, {sql_str(resolved_space_id)},\n"
                f"  {sql_str(run.config_hash)}, {sql_str(run.run_id)}, NULL,\n"
                f"  {sql_str(json.dumps(payload, ensure_ascii=False))}\n"
                f")"
            )
    else:
        prev_run: BenchmarkRunRecord | None = None
        for idx, run in enumerate(full_runs, start=1):
            diff = history.compare_runs(prev_run, run) if prev_run is not None else None
            target = "Agent" if run.mode == "agent" else "Chat"
            baseline_score = prev_run.accuracy_pct if prev_run else run.accuracy_pct
            score_delta = diff.delta_accuracy if diff else 0.0
            fixed_cnt = len(diff.fixed) if diff else 0
            regressed_cnt = len(diff.regressed) if diff else 0
            decision = "ROLL_BACK" if regressed_cnt > 0 else "KEEP"
            cfg_ver_id = f"cfg_{run.run_id}_{run.config_hash[:8]}"

            dml.append(
                f"MERGE INTO {prefix}.genie_opt_runs AS t\n"
                f"USING (SELECT {sql_str(run.run_id)} AS run_id) AS s\n"
                f"ON t.run_id = s.run_id\n"
                f"WHEN NOT MATCHED THEN INSERT (\n"
                f"  run_id, session_id, space_id, space_name, benchmark_execution_target,\n"
                f"  benchmark_id, benchmark_version_or_hash, iteration, parent_run_id,\n"
                f"  baseline_config_version_id, candidate_config_version_id, target_cluster,\n"
                f"  repair_lever, status, started_at, ended_at, baseline_score, candidate_score,\n"
                f"  score_delta, fixed_count, regressed_count, unchanged_bad_count,\n"
                f"  unchanged_good_count, excluded_count, decision, notes\n"
                f") VALUES (\n"
                f"  {sql_str(run.run_id)}, {sql_str(run.env)}, {sql_str(resolved_space_id)},\n"
                f"  {sql_str(run.space_name)}, {sql_str(target)}, {sql_str(bundle.space.name)},\n"
                f"  {sql_str(run.config_hash)}, {idx}, {sql_str(prev_run.run_id if prev_run else None)},\n"
                f"  {sql_str(prev_run.config_hash if prev_run else None)}, {sql_str(cfg_ver_id)},\n"
                f"  NULL, NULL, 'kept', TIMESTAMP {sql_str(run.created_at)}, TIMESTAMP {sql_str(run.created_at)},\n"
                f"  {baseline_score}, {run.accuracy_pct}, {score_delta}, {fixed_cnt}, {regressed_cnt},\n"
                f"  {run.failed}, {run.passed}, {run.excluded}, {sql_str(decision)},\n"
                f"  {sql_str(f'mode={run.mode}; p50={run.p50_latency_ms}ms; p95={run.p95_latency_ms}ms')}\n"
                f")"
            )

            # Snapshot de configuração
            dml.append(
                f"MERGE INTO {prefix}.genie_opt_config_versions AS t\n"
                f"USING (SELECT {sql_str(cfg_ver_id)} AS config_version_id) AS s\n"
                f"ON t.config_version_id = s.config_version_id\n"
                f"WHEN NOT MATCHED THEN INSERT (\n"
                f"  config_version_id, run_id, space_id, version_label, parent_config_version_id,\n"
                f"  captured_at, captured_by, config_hash, config_json, changed_surfaces, change_summary\n"
                f") VALUES (\n"
                f"  {sql_str(cfg_ver_id)}, {sql_str(run.run_id)}, {sql_str(resolved_space_id)},\n"
                f"  'after', NULL, TIMESTAMP {sql_str(run.created_at)}, 'genieops-cli',\n"
                f"  {sql_str(run.config_hash)}, {sql_str(compiled_json if run.config_hash == current_cfg_hash else '{}')},\n"
                f"  'serialized_space_v2', {sql_str(f'Snapshot exportado do ambiente {run.env}')}\n"
                f")"
            )

            # Resultados por pergunta
            for item in run.items:
                eval_res_id = f"{run.run_id}_{item.case_id}"
                eval_type = "Agent" if item.mode == "agent" else "Chat"
                strategy = (
                    "multi_step_agent_analysis"
                    if item.mode == "agent" and not item.expected_sql
                    else "single_sql_answer"
                )
                valid_fail = "TRUE" if item.status == "BAD" else "FALSE"
                dml.append(
                    f"MERGE INTO {prefix}.genie_opt_eval_results AS t\n"
                    f"USING (SELECT {sql_str(eval_res_id)} AS eval_result_id) AS s\n"
                    f"ON t.eval_result_id = s.eval_result_id\n"
                    f"WHEN NOT MATCHED THEN INSERT (\n"
                    f"  eval_result_id, eval_run_id, run_id, space_id, benchmark_id,\n"
                    f"  benchmark_version_or_hash, eval_type, evaluated_at, question_id,\n"
                    f"  question_text, benchmark_field_strategy, assessment, valid_tuning_failure,\n"
                    f"  exclusion_reason, primary_failure, secondary_signal, failure_cluster,\n"
                    f"  expected_sql_hash, generated_sql_hash, generated_sql, evaluation_note_hash,\n"
                    f"  expected_result_digest, actual_result_digest, judge_notes, latency_ms, error_message\n"
                    f") VALUES (\n"
                    f"  {sql_str(eval_res_id)}, {sql_str(run.run_id)}, {sql_str(run.run_id)},\n"
                    f"  {sql_str(resolved_space_id)}, {sql_str(bundle.space.name)}, {sql_str(run.config_hash)},\n"
                    f"  {sql_str(eval_type)}, TIMESTAMP {sql_str(run.created_at)}, {sql_str(item.case_id)},\n"
                    f"  {sql_str(item.question)}, {sql_str(strategy)}, {sql_str(item.status)}, {valid_fail},\n"
                    f"  NULL, NULL, NULL, {sql_str(item.domain)},\n"
                    f"  {sql_str(_sha256_short(item.expected_sql))}, {sql_str(_sha256_short(item.generated_sql))},\n"
                    f"  {sql_str(item.generated_sql)}, NULL, NULL, NULL,\n"
                    f"  {sql_str('; '.join(item.details) if item.details else None)},\n"
                    f"  {int(round(item.latency_ms))}, {sql_str(item.error_message)}\n"
                    f")"
                )

            # Análise de causa raiz / reparo para falhas
            diag = diagnose_run(run, bundle)
            for d_idx, d in enumerate(diag.diagnoses, start=1):
                analysis_id = f"ana_{run.run_id}_{d_idx:02d}"
                dml.append(
                    f"MERGE INTO {prefix}.genie_opt_repair_analysis AS t\n"
                    f"USING (SELECT {sql_str(analysis_id)} AS analysis_id) AS s\n"
                    f"ON t.analysis_id = s.analysis_id\n"
                    f"WHEN NOT MATCHED THEN INSERT (\n"
                    f"  analysis_id, run_id, space_id, created_at, cluster_id, affected_question_ids,\n"
                    f"  root_cause, evidence_summary, selected_lever, rejected_levers, config_surface,\n"
                    f"  planned_patch_summary, expected_fix_count, regression_risk, benchmark_leakage_check,\n"
                    f"  acceptance_decision, reflection, next_hypothesis\n"
                    f") VALUES (\n"
                    f"  {sql_str(analysis_id)}, {sql_str(run.run_id)}, {sql_str(resolved_space_id)},\n"
                    f"  TIMESTAMP {sql_str(run.created_at)}, {sql_str(d.root_cause_class)},\n"
                    f"  {sql_str(json.dumps([d.case_id]))}, {sql_str(d.root_cause_class)},\n"
                    f"  {sql_str('; '.join(d.evidence))}, {sql_str(d.recommended_lever)},\n"
                    f"  {sql_str(d.avoid_antipattern)}, {sql_str(d.recommended_lever)},\n"
                    f"  {sql_str(d.proposed_action)}, 1, 'LOW', 'PASS', 'PROPOSED', NULL, NULL\n"
                    f")"
                )

            prev_run = run

    plan = UCExportPlan(
        space_name=bundle.space.name,
        catalog=cat_clean,
        schema=sch_clean,
        schema_mode=schema_mode,
        runs_exported=len(full_runs),
        ddl_statements=ddl,
        dml_statements=dml,
    )

    if output_sql_path is not None:
        output_sql_path.parent.mkdir(parents=True, exist_ok=True)
        output_sql_path.write_text(plan.full_sql(), encoding="utf-8")
        plan.output_sql_path = output_sql_path

    return plan


def execute_uc_export_plan(
    plan: UCExportPlan,
    client: DatabricksClient,
    warehouse_id: str | None = None,
) -> UCExportPlan:
    """
    Executa explicitamente o plano de exportação Delta no SQL Warehouse, aplicando
    a guarda estrita `assert_uc_export_sql_safe` em cada instrução.
    """
    for stmt in plan.ddl_statements + plan.dml_statements:
        assert_uc_export_sql_safe(stmt, plan.catalog, plan.schema)
        client.execute_uc_export_sql(stmt, catalog=plan.catalog, schema=plan.schema, warehouse_id=warehouse_id)
    plan.executed = True
    return plan
