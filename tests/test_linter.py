"""Testes do Genie Health Check (Linter estático + EXPLAIN read-only + guarda de SQL)."""

from __future__ import annotations

import pytest

from genieops.databricks_client import assert_read_only_sql
from genieops.linter import find_unqualified_columns, lint_space
from genieops.models import (
    ColumnConfig,
    ExampleQuestionSql,
    JoinEndpoint,
    JoinSpec,
    SpaceBundle,
    SqlSnippetFilter,
    TableSource,
)
from tests.conftest import FakeCompletedProcess, make_json_response


def test_exemplo_vendas_passes_linter_cleanly(exemplo_bundle: SpaceBundle) -> None:
    report = lint_space(exemplo_bundle)
    assert report.passed is True
    assert report.error_count == 0
    assert report.warning_count == 0
    assert report.health_score >= 95


def test_unqualified_columns_detection() -> None:
    assert find_unqualified_columns("fct_pedidos.status_pedido = 'Faturado'") == []
    assert find_unqualified_columns("`fct_pedidos`.`id_cliente` = `dim_clientes`.`id_cliente`") == []
    assert find_unqualified_columns("SUM(orders.amount) / NULLIF(COUNT(orders.id), 0)") == []

    bad = find_unqualified_columns("`order_date` = LAST_DAY(`order_date`)")
    assert "order_date" in bad

    bad2 = find_unqualified_columns("status_pedido = 'Faturado' AND valor > 100")
    assert "status_pedido" in bad2
    assert "valor" in bad2


def test_linter_catches_leakage_unqualified_sql_and_text_smells(exemplo_bundle: SpaceBundle) -> None:
    mutated = exemplo_bundle.model_copy(deep=True)

    # 1. Benchmark Leakage (copia exata de um benchmark em example_question_sqls)
    bmk0 = mutated.benchmarks.questions[0]
    mutated.instructions.example_question_sqls.append(
        ExampleQuestionSql(question=bmk0.question, sql=bmk0.ground_truth_sql or "")
    )

    # 2. Coluna nua em sql_snippet e join_spec
    mutated.instructions.sql_snippets.filters.append(
        SqlSnippetFilter(display_name="Filtro ruim", sql="status_pedido = 'Faturado'")
    )
    mutated.instructions.join_specs.append(
        JoinSpec(
            left=JoinEndpoint(identifier="a.b.t1", alias="t1"),
            right=JoinEndpoint(identifier="a.b.t2", alias="t2"),
            condition="id_cliente = t2.id_cliente",
        )
    )

    # 3. Entity matching indevido em ID e texto com filtro literal
    mutated.sources.tables[0].column_configs.append(
        ColumnConfig(column_name="hash_interno", description=["Hash"], enable_entity_matching=True)
    )
    mutated.instructions.text_instructions.append("Sempre filtre WHERE status_pedido = 'Faturado'.")

    report = lint_space(mutated)
    codes = {i.code for i in report.issues}
    assert "LEAK001" in codes
    assert "SQL001" in codes
    assert "COL003" in codes
    assert "TXT001" in codes
    assert report.passed is False


def test_linter_source_limits(exemplo_bundle: SpaceBundle) -> None:
    mutated = exemplo_bundle.model_copy(deep=True)
    for idx in range(30):
        mutated.sources.tables.append(
            TableSource(identifier=f"cat.sch.tbl_{idx}", description=["Tabela extra"])
        )
    report = lint_space(mutated)
    assert any(i.code == "SRC001" and i.severity == "ERROR" for i in report.issues)


def test_linter_validate_sql_with_mock_explain(
    exemplo_bundle: SpaceBundle, mock_client_factory
) -> None:
    def handler(cmd: list[str]) -> FakeCompletedProcess:
        cmd_str = " ".join(cmd)
        if "bmk_fail_table" in cmd_str:
            return FakeCompletedProcess(returncode=1, stderr="[TABLE_OR_VIEW_NOT_FOUND] bmk_fail_table")
        return make_json_response({"columns": ["plan"], "rows": [["== Physical Plan =="]]})

    client, runner = mock_client_factory(handler)
    mutated = exemplo_bundle.model_copy(deep=True)
    mutated.benchmarks.questions[0].ground_truth_sql = "SELECT * FROM analytics_dev.sales_gold.bmk_fail_table"

    report = lint_space(mutated, validate_sql=True, client=client, warehouse_id="wh_test")
    assert report.sql_validated_count == 33  # 3 examples + 30 chat benchmarks
    assert report.sql_failed_count == 1
    assert any(i.code == "SQLVAL" and i.severity == "ERROR" for i in report.issues)
    assert len(runner.calls) == 33


def test_readonly_sql_guard_blocks_mutations() -> None:
    assert_read_only_sql("SELECT 1")
    assert_read_only_sql("EXPLAIN SELECT * FROM cat.sch.tbl")
    assert_read_only_sql("DESCRIBE TABLE cat.sch.tbl")

    with pytest.raises(ValueError):
        assert_read_only_sql("DROP TABLE cat.sch.tbl")
    with pytest.raises(ValueError):
        assert_read_only_sql("DELETE FROM cat.sch.tbl WHERE id = 1")
    with pytest.raises(ValueError):
        assert_read_only_sql("WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x")
