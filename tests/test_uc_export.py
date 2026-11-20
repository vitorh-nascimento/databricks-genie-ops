"""Testes unitários para exportação do histórico SQLite para tabelas Delta no Unity Catalog."""

from __future__ import annotations

from pathlib import Path

import pytest

from genieops.benchmark import run_benchmark
from genieops.history import HistoryStore
from genieops.uc_export import (
    assert_uc_export_sql_safe,
    build_uc_export_plan,
    execute_uc_export_plan,
)
from tests.conftest import make_json_response


def test_build_uc_export_plan_four_tables_and_events(exemplo_bundle, tmp_path: Path):
    history = HistoryStore(db_path=tmp_path / "history.db")
    run_benchmark(exemplo_bundle, env_name="dev", mode="offline", history=history)

    out_sql = tmp_path / "export_four.sql"
    plan = build_uc_export_plan(
        exemplo_bundle,
        history,
        catalog="analytics-ops",
        schema="genieops_audit",
        schema_mode="four_tables",
        space_id="sp_dev_123",
        output_sql_path=out_sql,
    )

    assert plan.runs_exported == 1
    assert len(plan.ddl_statements) == 4
    assert len(plan.dml_statements) >= 24  # 1 run + 1 config + 22 eval items
    assert out_sql.exists()

    sql_text = plan.full_sql()
    assert "`analytics-ops`.genieops_audit.genie_opt_runs" in sql_text
    assert "`analytics-ops`.genieops_audit.genie_opt_config_versions" in sql_text
    assert "`analytics-ops`.genieops_audit.genie_opt_eval_results" in sql_text
    assert "`analytics-ops`.genieops_audit.genie_opt_repair_analysis" in sql_text

    # Modo single event table
    ev_plan = build_uc_export_plan(
        exemplo_bundle,
        history,
        catalog="analytics_ops",
        schema="genieops_audit",
        schema_mode="events",
    )
    assert len(ev_plan.ddl_statements) == 1
    assert len(ev_plan.dml_statements) == 1
    assert "analytics_ops.genieops_audit.genie_opt_events" in ev_plan.full_sql()


def test_uc_export_safety_guard_blocks_unsafe_statements():
    # Permitidos
    assert_uc_export_sql_safe(
        "CREATE TABLE IF NOT EXISTS cat.sch.genie_opt_runs (run_id STRING) USING DELTA",
        catalog="cat",
        schema="sch",
    )
    assert_uc_export_sql_safe(
        "MERGE INTO cat.sch.genie_opt_eval_results AS t USING (SELECT '1' AS eval_result_id) AS s ON t.eval_result_id = s.eval_result_id WHEN NOT MATCHED THEN INSERT (eval_result_id) VALUES ('1')",
        catalog="cat",
        schema="sch",
    )

    # Bloqueados: tabela de negócio fora da allowlist
    with pytest.raises(ValueError, match="allowlist"):
        assert_uc_export_sql_safe(
            "INSERT INTO cat.sch.fct_pedidos VALUES (1)",
            catalog="cat",
            schema="sch",
        )

    # Bloqueados: comandos destrutivos
    for bad in (
        "DROP TABLE cat.sch.genie_opt_runs",
        "TRUNCATE TABLE cat.sch.genie_opt_runs",
        "DELETE FROM cat.sch.genie_opt_runs WHERE run_id = '1'",
    ):
        with pytest.raises(ValueError):
            assert_uc_export_sql_safe(bad, catalog="cat", schema="sch")


def test_execute_uc_export_plan_calls_cli(exemplo_bundle, tmp_path: Path, mock_client_factory):
    history = HistoryStore(db_path=tmp_path / "history.db")
    run_benchmark(exemplo_bundle, env_name="dev", mode="offline", history=history)

    plan = build_uc_export_plan(
        exemplo_bundle,
        history,
        catalog="analytics_ops",
        schema="genieops_audit",
        schema_mode="events",
    )
    client, runner = mock_client_factory(lambda _cmd: make_json_response({"columns": [], "rows": []}))

    executed_plan = execute_uc_export_plan(plan, client=client, warehouse_id="wh_ops")
    assert executed_plan.executed is True
    assert len(runner.calls) == 2  # 1 DDL + 1 MERGE
