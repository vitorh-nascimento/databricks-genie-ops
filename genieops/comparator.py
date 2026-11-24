"""Motor de comparação de equivalência de Result Sets (tabular e numérico com tolerância)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from genieops.databricks_client import QueryResult


@dataclass
class ComparisonResult:
    """Resultado detalhado da comparação entre dois Result Sets SQL."""

    equivalent: bool
    reason: str
    expected_row_count: int
    actual_row_count: int
    column_mapping: list[tuple[str, str]] = field(default_factory=list)
    differences: list[str] = field(default_factory=list)


def _try_to_float(val: Any) -> float | None:
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, str):
        s = val.strip().replace(",", "")
        if not s:
            return None
        try:
            return float(Decimal(s))
        except (InvalidOperation, ValueError):
            return None
    return None


def _normalize_cell(val: Any) -> tuple[str, Any]:
    """Normaliza uma célula para comparação consistente entre tipos do SQL Warehouse."""
    if val is None:
        return ("null", None)
    if isinstance(val, bool):
        return ("bool", val)
    if isinstance(val, str):
        low = val.strip().lower()
        if low in ("null", "none", ""):
            return ("null", None)
        if low in ("true", "false"):
            return ("bool", low == "true")
    num = _try_to_float(val)
    if num is not None and not math.isnan(num):
        return ("num", num)
    return ("str", str(val).strip().lower())


def _cells_equal(a: Any, b: Any, rel_tol: float = 1e-4, abs_tol: float = 1e-2) -> bool:
    ta, va = _normalize_cell(a)
    tb, vb = _normalize_cell(b)
    if ta != tb:
        # Trata 1/0 vs true/false comumente retornado por SQL booleano
        if {ta, tb} == {"bool", "num"}:
            bool_val = va if ta == "bool" else vb
            num_val = va if ta == "num" else vb
            return (bool_val and num_val == 1.0) or (not bool_val and num_val == 0.0)
        return False
    if ta == "num":
        return math.isclose(va, vb, rel_tol=rel_tol, abs_tol=abs_tol)
    return va == vb


def _row_sort_key(row: list[Any]) -> tuple[Any, ...]:
    key_parts = []
    for cell in row:
        t, v = _normalize_cell(cell)
        if t == "null":
            key_parts.append((0, ""))
        elif t == "bool":
            key_parts.append((1, int(v)))
        elif t == "num":
            # Arredonda levemente para ordenação estável antes da comparação com tolerância
            key_parts.append((2, round(v, 4)))
        else:
            key_parts.append((3, str(v)))
    return tuple(key_parts)


def _columns_equal_as_multiset(
    exp_values: list[Any],
    act_values: list[Any],
    rel_tol: float,
    abs_tol: float,
) -> bool:
    """Compara duas colunas como multiconjuntos de valores (ignora ordem das linhas)."""
    exp_sorted = sorted(exp_values, key=lambda v: _row_sort_key([v]))
    act_sorted = sorted(act_values, key=lambda v: _row_sort_key([v]))
    return all(
        _cells_equal(e, a, rel_tol=rel_tol, abs_tol=abs_tol)
        for e, a in zip(exp_sorted, act_sorted)
    )


def _candidate_columns(
    expected_cols: list[str],
    actual_cols: list[str],
    exp_rows: list[list[Any]],
    act_rows: list[list[Any]],
    rel_tol: float,
    abs_tol: float,
) -> list[list[int]]:
    """
    Para cada coluna esperada, lista as colunas obtidas cujo conteúdo é compatível.

    O casamento é feito pelos VALORES (não pelo alias), porque o Genie escolhe nomes livremente
    (`receita` vs `receita_liquida_total`) e frequentemente devolve as colunas em outra ordem.
    Colunas com o mesmo nome normalizado vêm primeiro na lista de candidatas.
    """
    act_norm = [c.strip().lower() for c in actual_cols]
    candidates: list[list[int]] = []
    for i, ec in enumerate(expected_cols):
        exp_values = [row[i] for row in exp_rows]
        matches = [
            j
            for j in range(len(actual_cols))
            if _columns_equal_as_multiset(
                exp_values, [row[j] for row in act_rows], rel_tol=rel_tol, abs_tol=abs_tol
            )
        ]
        matches.sort(key=lambda j: act_norm[j] != ec.strip().lower())
        candidates.append(matches)
    return candidates


def _rows_match(
    exp_rows: list[list[Any]],
    act_rows: list[list[Any]],
    indices: list[int],
    rel_tol: float,
    abs_tol: float,
    enforce_order: bool,
) -> list[str]:
    """Compara linha a linha usando o mapeamento de colunas; retorna as divergências (máx. 10)."""
    projected = [[row[idx] for idx in indices] for row in act_rows]
    if enforce_order:
        exp_ordered, act_ordered = list(exp_rows), projected
    else:
        exp_ordered = sorted(exp_rows, key=_row_sort_key)
        act_ordered = sorted(projected, key=_row_sort_key)

    diffs: list[str] = []
    for r_idx, (erow, arow) in enumerate(zip(exp_ordered, act_ordered)):
        for c_idx, (ecell, acell) in enumerate(zip(erow, arow)):
            if not _cells_equal(ecell, acell, rel_tol=rel_tol, abs_tol=abs_tol):
                diffs.append(
                    f"Linha {r_idx + 1}, coluna #{c_idx + 1}: esperado={ecell!r}, obtido={acell!r}"
                )
                if len(diffs) >= 10:
                    return diffs
    return diffs


def _search_alignment(
    candidates: list[list[int]],
    check: Any,
    max_attempts: int = 500,
) -> list[int] | None:
    """Busca (com backtracking limitado) uma atribuição injetiva coluna esperada → obtida válida."""
    attempts = 0

    def dfs(pos: int, chosen: list[int]) -> list[int] | None:
        nonlocal attempts
        if pos == len(candidates):
            attempts += 1
            return list(chosen) if check(chosen) else None
        for j in candidates[pos]:
            if j in chosen or attempts >= max_attempts:
                continue
            chosen.append(j)
            found = dfs(pos + 1, chosen)
            chosen.pop()
            if found is not None:
                return found
        return None

    return dfs(0, [])


def compare_result_sets(
    expected: QueryResult,
    actual: QueryResult,
    rel_tol: float = 1e-4,
    abs_tol: float = 1e-2,
    enforce_order: bool = False,
    allow_extra_columns: bool = True,
) -> ComparisonResult:
    """
    Compara dois Result Sets SQL (Ground Truth vs SQL gerado pelo Genie).
    Evita falsos negativos quando o Genie escreve SQL diferente porém matematicamente equivalente:
    - aliases e ordem de colunas diferentes (colunas casadas pelos valores, não pelo nome);
    - colunas extras de contexto no resultado do Genie (ex.: `id_cliente`, `total_pedidos`),
      desde que todas as colunas esperadas estejam presentes e a contagem de linhas bata.
    """
    exp_rows = expected.rows or []
    act_rows = actual.rows or []

    if len(exp_rows) != len(act_rows):
        return ComparisonResult(
            equivalent=False,
            reason=f"Contagem de linhas divergente: esperado={len(exp_rows)}, obtido={len(act_rows)}.",
            expected_row_count=len(exp_rows),
            actual_row_count=len(act_rows),
        )

    if len(exp_rows) == 0:
        return ComparisonResult(
            equivalent=True,
            reason="Ambos os Result Sets estão vazios (0 linhas).",
            expected_row_count=0,
            actual_row_count=0,
        )

    exp_cols = expected.columns or [f"col_{i}" for i in range(len(exp_rows[0]))]
    act_cols = actual.columns or [f"col_{i}" for i in range(len(act_rows[0]))]

    if len(act_cols) < len(exp_cols) or (not allow_extra_columns and len(act_cols) != len(exp_cols)):
        return ComparisonResult(
            equivalent=False,
            reason=f"Quantidade de colunas divergente: esperado={len(exp_cols)} ({exp_cols}), obtido={len(act_cols)} ({act_cols}).",
            expected_row_count=len(exp_rows),
            actual_row_count=len(act_rows),
        )

    candidates = _candidate_columns(exp_cols, act_cols, exp_rows, act_rows, rel_tol, abs_tol)
    missing = [exp_cols[i] for i, cands in enumerate(candidates) if not cands]
    if missing:
        # Para diagnóstico, compara posicionalmente quando a contagem de colunas é igual
        diffs: list[str] = []
        if len(act_cols) == len(exp_cols):
            diffs = _rows_match(
                exp_rows, act_rows, list(range(len(act_cols))), rel_tol, abs_tol, enforce_order
            )
        return ComparisonResult(
            equivalent=False,
            reason=f"Nenhuma coluna obtida tem os mesmos valores de {missing} (obtido: {act_cols}).",
            expected_row_count=len(exp_rows),
            actual_row_count=len(act_rows),
            differences=diffs,
        )

    indices = _search_alignment(
        candidates,
        lambda chosen: not _rows_match(exp_rows, act_rows, chosen, rel_tol, abs_tol, enforce_order),
    )
    if indices is None:
        fallback = [cands[0] for cands in candidates]
        return ComparisonResult(
            equivalent=False,
            reason="Colunas individualmente compatíveis, mas as linhas não se combinam da mesma forma (ou a ordem exigida diverge).",
            expected_row_count=len(exp_rows),
            actual_row_count=len(act_rows),
            column_mapping=[(exp_cols[i], act_cols[j]) for i, j in enumerate(fallback)],
            differences=_rows_match(exp_rows, act_rows, fallback, rel_tol, abs_tol, enforce_order),
        )

    col_mapping = [(exp_cols[i], act_cols[j]) for i, j in enumerate(indices)]
    extra = [c for j, c in enumerate(act_cols) if j not in indices]
    reason = "Result Sets matematicamente equivalentes dentro da tolerância configurada."
    if extra:
        reason += f" Colunas extras ignoradas: {extra}."
    return ComparisonResult(
        equivalent=True,
        reason=reason,
        expected_row_count=len(exp_rows),
        actual_row_count=len(act_rows),
        column_mapping=col_mapping,
    )
