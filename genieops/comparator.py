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


def _align_columns(
    expected_cols: list[str],
    actual_cols: list[str],
) -> tuple[list[int], list[tuple[str, str]]] | None:
    """
    Alinha colunas de `actual` à ordem de `expected`.
    1) Se nomes normalizados baterem (mesmo em ordem diferente), reordena por nome.
    2) Se quantidade de colunas for igual mas aliases diferirem (ex: SUM(valor) vs total_gasto),
       alinha posicionalmente.
    """
    if len(expected_cols) != len(actual_cols):
        return None

    exp_norm = [c.strip().lower() for c in expected_cols]
    act_norm = [c.strip().lower() for c in actual_cols]

    if sorted(exp_norm) == sorted(act_norm):
        used: set[int] = set()
        indices: list[int] = []
        mapping: list[tuple[str, str]] = []
        for i, ec in enumerate(exp_norm):
            for j, ac in enumerate(act_norm):
                if ac == ec and j not in used:
                    used.add(j)
                    indices.append(j)
                    mapping.append((expected_cols[i], actual_cols[j]))
                    break
        return indices, mapping

    # Fallback posicional (evita falso negativo por diferença de alias no SELECT)
    indices = list(range(len(actual_cols)))
    mapping = list(zip(expected_cols, actual_cols))
    return indices, mapping


def compare_result_sets(
    expected: QueryResult,
    actual: QueryResult,
    rel_tol: float = 1e-4,
    abs_tol: float = 1e-2,
    enforce_order: bool = False,
) -> ComparisonResult:
    """
    Compara dois Result Sets SQL (Ground Truth vs SQL gerado pelo Genie).
    Evita falsos negativos quando o Genie escreve SQL diferente porém matematicamente equivalente.
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

    alignment = _align_columns(exp_cols, act_cols)
    if alignment is None:
        return ComparisonResult(
            equivalent=False,
            reason=f"Quantidade de colunas divergente: esperado={len(exp_cols)} ({exp_cols}), obtido={len(act_cols)} ({act_cols}).",
            expected_row_count=len(exp_rows),
            actual_row_count=len(act_rows),
        )

    col_indices, col_mapping = alignment
    reordered_act = [[row[idx] for idx in col_indices] for row in act_rows]

    if enforce_order:
        exp_ordered = list(exp_rows)
        act_ordered = reordered_act
    else:
        exp_ordered = sorted(exp_rows, key=_row_sort_key)
        act_ordered = sorted(reordered_act, key=_row_sort_key)

    diffs: list[str] = []
    for r_idx, (erow, arow) in enumerate(zip(exp_ordered, act_ordered)):
        for c_idx, (ecell, acell) in enumerate(zip(erow, arow)):
            if not _cells_equal(ecell, acell, rel_tol=rel_tol, abs_tol=abs_tol):
                col_label = exp_cols[c_idx] if c_idx < len(exp_cols) else f"col_{c_idx}"
                diffs.append(
                    f"Linha {r_idx + 1}, coluna '{col_label}': esperado={ecell!r}, obtido={acell!r}"
                )
                if len(diffs) >= 10:
                    break
        if len(diffs) >= 10:
            break

    if diffs:
        return ComparisonResult(
            equivalent=False,
            reason=f"Divergência de valores em {len(diffs)} célula(s).",
            expected_row_count=len(exp_rows),
            actual_row_count=len(act_rows),
            column_mapping=col_mapping,
            differences=diffs,
        )

    return ComparisonResult(
        equivalent=True,
        reason="Result Sets matematicamente equivalentes dentro da tolerância configurada.",
        expected_row_count=len(exp_rows),
        actual_row_count=len(act_rows),
        column_mapping=col_mapping,
    )
