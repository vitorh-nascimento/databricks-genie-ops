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


def test_matches_columns_by_values_when_aliases_and_order_differ() -> None:
    # Caso real (bmk_16): Genie usou outros aliases e outra ordem de colunas para a mesma resposta
    expected = QueryResult(
        columns=["segmento", "receita", "share_pct"],
        rows=[["Interno", 544548.12, 2.8], ["Enterprise", 9000000.0, 46.3]],
    )
    actual = QueryResult(
        columns=["participacao_pct", "receita_liquida", "segmento"],
        rows=[[46.3, 9000000.0, "Enterprise"], [2.8, 544548.12, "Interno"]],
    )
    res = compare_result_sets(expected, actual, rel_tol=1e-3, abs_tol=0.05)
    assert res.equivalent is True
    assert ("segmento", "segmento") in res.column_mapping


def test_ignores_extra_context_columns_from_genie() -> None:
    # Caso real (bmk_07/bmk_25): Genie devolve id_cliente / pedidos_faturados a mais
    expected = QueryResult(columns=["nome_cliente", "receita"], rows=[["A", 500.0], ["B", 400.0]])
    actual = QueryResult(
        columns=["id_cliente", "nome_cliente", "receita_liquida"],
        rows=[[1, "A", 500.0], [2, "B", 400.0]],
    )
    res = compare_result_sets(expected, actual, enforce_order=True)
    assert res.equivalent is True
    assert "id_cliente" in res.reason

    strict = compare_result_sets(expected, actual, allow_extra_columns=False)
    assert strict.equivalent is False


def test_columns_with_same_values_must_still_combine_row_by_row() -> None:
    # Cada coluna isoladamente bate, mas os pares (regiao, total) estão trocados
    expected = QueryResult(columns=["regiao", "total"], rows=[["Sul", 100.0], ["Norte", 200.0]])
    actual = QueryResult(columns=["regiao", "total"], rows=[["Sul", 200.0], ["Norte", 100.0]])
    assert compare_result_sets(expected, actual).equivalent is False


def test_disambiguates_columns_with_identical_value_sets() -> None:
    expected = QueryResult(columns=["a", "b"], rows=[[1, 2], [2, 1]])
    actual = QueryResult(columns=["x", "y"], rows=[[2, 1], [1, 2]])
    assert compare_result_sets(expected, actual, enforce_order=True).equivalent is True


def test_enforce_order_for_top_n_rankings() -> None:
    expected = QueryResult(columns=["cliente", "total"], rows=[["A", 500], ["B", 400]])
    actual_swapped = QueryResult(columns=["cliente", "total"], rows=[["B", 400], ["A", 500]])
    assert compare_result_sets(expected, actual_swapped, enforce_order=False).equivalent is True
    assert compare_result_sets(expected, actual_swapped, enforce_order=True).equivalent is False
