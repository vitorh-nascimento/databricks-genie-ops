"""Testes do motor de comparação de equivalência de Result Sets."""

from __future__ import annotations

from genieops.comparator import compare_result_sets
from genieops.databricks_client import QueryResult


def test_equivalent_result_sets_despite_alias_and_row_order_differences() -> None:
    expected = QueryResult(
        columns=["regiao", "receita_liquida"],
        rows=[["Sudeste", "150000.50"], ["Sul", "82000.10"]],
    )
    actual = QueryResult(
        columns=["region_name", "total_sales"],
        rows=[["Sul", 82000.104], ["Sudeste", 150000.50]],
    )
    res = compare_result_sets(expected, actual, rel_tol=1e-4, abs_tol=1e-2)
    assert res.equivalent is True


def test_reorders_columns_by_name_when_shuffled() -> None:
    expected = QueryResult(columns=["canal", "total"], rows=[["Pix", 500], ["Boleto", 300]])
    actual = QueryResult(columns=["total", "canal"], rows=[[300.0, "Boleto"], [500.0, "Pix"]])
    res = compare_result_sets(expected, actual)
    assert res.equivalent is True


def test_detects_value_row_and_column_mismatches() -> None:
    expected = QueryResult(columns=["regiao", "total"], rows=[["Sudeste", 1000.0]])
    actual_val_diff = QueryResult(columns=["regiao", "total"], rows=[["Sudeste", 1050.0]])
    res_val = compare_result_sets(expected, actual_val_diff)
    assert res_val.equivalent is False
    assert len(res_val.differences) == 1

    actual_row_diff = QueryResult(columns=["regiao", "total"], rows=[["Sudeste", 1000.0], ["Sul", 50.0]])
    assert compare_result_sets(expected, actual_row_diff).equivalent is False

    actual_col_diff = QueryResult(columns=["regiao"], rows=[["Sudeste"]])
    assert compare_result_sets(expected, actual_col_diff).equivalent is False


def test_enforce_order_for_top_n_rankings() -> None:
    expected = QueryResult(columns=["cliente", "total"], rows=[["A", 500], ["B", 400]])
    actual_swapped = QueryResult(columns=["cliente", "total"], rows=[["B", 400], ["A", 500]])
    assert compare_result_sets(expected, actual_swapped, enforce_order=False).equivalent is True
    assert compare_result_sets(expected, actual_swapped, enforce_order=True).equivalent is False
