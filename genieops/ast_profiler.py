"""Profiling avançado com parsing AST (sqlglot/Databricks) sobre system.query.history."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp


@dataclass
class JoinPattern:
    left_table: str
    right_table: str
    left_column: str
    right_column: str
    count: int


@dataclass
class FilterPattern:
    table: str
    column: str
    operator: str
    count: int
    sample_values: list[str] = field(default_factory=list)


@dataclass
class AggregationPattern:
    expression_sql: str
    function_name: str
    table: str | None
    count: int


@dataclass
class ASTProfileResult:
    queries_parsed: int = 0
    queries_failed: int = 0
    table_counts: dict[str, int] = field(default_factory=dict)
    column_counts: dict[str, int] = field(default_factory=dict)
    join_patterns: list[JoinPattern] = field(default_factory=list)
    filter_patterns: list[FilterPattern] = field(default_factory=list)
    aggregation_patterns: list[AggregationPattern] = field(default_factory=list)


def _normalize_table_name(tbl: exp.Table) -> str:
    parts = [p for p in (tbl.catalog, tbl.db, tbl.name) if p]
    return ".".join(parts).lower()


def _short_name(identifier: str) -> str:
    return identifier.split(".")[-1].lower()


def _resolve_alias_map(tree: exp.Expression) -> dict[str, str]:
    """Mapeia alias (ou nome curto da tabela) -> nome normalizado da tabela na query."""
    aliases: dict[str, str] = {}
    for tbl in tree.find_all(exp.Table):
        full = _normalize_table_name(tbl)
        if not full:
            continue
        short = _short_name(full)
        aliases[short] = full
        if tbl.alias:
            aliases[tbl.alias.lower()] = full
    return aliases


def _resolve_column_table(
    col: exp.Column,
    aliases: dict[str, str],
    default_table: str | None,
) -> tuple[str, str]:
    col_name = col.name.lower()
    raw_tbl = (col.table or "").lower()
    if raw_tbl and raw_tbl in aliases:
        return aliases[raw_tbl], col_name
    if raw_tbl:
        return raw_tbl, col_name
    return default_table or "unknown", col_name


def analyze_query_history_ast(
    sql_statements: list[str],
    known_tables: list[str] | None = None,
    min_occurrences: int = 1,
) -> ASTProfileResult:
    """
    Faz parsing AST (dialeto Databricks) de um lote de consultas de `system.query.history`
    para extrair padrões reais de JOIN, filtros WHERE e medidas/agregações frequentes.
    """
    known_map: dict[str, str] = {}
    for kt in known_tables or []:
        known_map[kt.lower()] = kt
        known_map[_short_name(kt)] = kt

    def canonical_table(name: str) -> str:
        low = name.lower()
        if low in known_map:
            return known_map[low]
        short = _short_name(low)
        return known_map.get(short, name)

    result = ASTProfileResult()
    table_counter: Counter[str] = Counter()
    col_counter: Counter[str] = Counter()
    join_counter: Counter[tuple[str, str, str, str]] = Counter()
    filter_counter: Counter[tuple[str, str, str]] = Counter()
    filter_values: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    agg_counter: Counter[tuple[str, str, str | None]] = Counter()

    for raw_sql in sql_statements:
        if not raw_sql or not raw_sql.strip():
            continue
        try:
            tree = sqlglot.parse_one(raw_sql, read="databricks")
        except Exception:
            result.queries_failed += 1
            continue

        result.queries_parsed += 1
        aliases = _resolve_alias_map(tree)
        tables_in_query = sorted({canonical_table(v) for v in aliases.values()})
        for tbl_name in tables_in_query:
            table_counter[tbl_name] += 1
        default_tbl = tables_in_query[0] if len(tables_in_query) == 1 else None

        # 1. Colunas referenciadas
        for col in tree.find_all(exp.Column):
            if not col.name:
                continue
            tbl_resolved, col_name = _resolve_column_table(col, aliases, default_tbl)
            ct = canonical_table(tbl_resolved)
            col_counter[f"{ct}.{col_name}"] += 1

        # 2. Padrões de JOIN (cláusulas ON com igualdade entre colunas de tabelas distintas)
        for join_node in tree.find_all(exp.Join):
            on_expr = join_node.args.get("on")
            if not on_expr:
                continue
            for eq in on_expr.find_all(exp.EQ):
                if isinstance(eq.left, exp.Column) and isinstance(eq.right, exp.Column):
                    lt, lc = _resolve_column_table(eq.left, aliases, default_tbl)
                    rt, rc = _resolve_column_table(eq.right, aliases, default_tbl)
                    lt_c, rt_c = canonical_table(lt), canonical_table(rt)
                    if lt_c == rt_c or lt_c == "unknown" or rt_c == "unknown":
                        continue
                    pair = (
                        (lt_c, rt_c, lc, rc)
                        if (lt_c, lc) <= (rt_c, rc)
                        else (rt_c, lt_c, rc, lc)
                    )
                    join_counter[pair] += 1

        # 3. Filtros WHERE frequentes (=, IN, LIKE/ILIKE, BETWEEN)
        for where_node in tree.find_all(exp.Where):
            for eq in where_node.find_all(exp.EQ):
                if isinstance(eq.left, exp.Column) and isinstance(eq.right, exp.Literal):
                    t, c = _resolve_column_table(eq.left, aliases, default_tbl)
                    key = (canonical_table(t), c, "=")
                    filter_counter[key] += 1
                    if eq.right.is_string and len(filter_values[key]) < 8:
                        filter_values[key].add(str(eq.right.this))
                elif isinstance(eq.right, exp.Column) and isinstance(eq.left, exp.Literal):
                    t, c = _resolve_column_table(eq.right, aliases, default_tbl)
                    key = (canonical_table(t), c, "=")
                    filter_counter[key] += 1
                    if eq.left.is_string and len(filter_values[key]) < 8:
                        filter_values[key].add(str(eq.left.this))

            for in_node in where_node.find_all(exp.In):
                if isinstance(in_node.this, exp.Column):
                    t, c = _resolve_column_table(in_node.this, aliases, default_tbl)
                    key = (canonical_table(t), c, "IN")
                    filter_counter[key] += 1
                    for val in in_node.expressions or []:
                        if isinstance(val, exp.Literal) and val.is_string and len(filter_values[key]) < 8:
                            filter_values[key].add(str(val.this))

            for like_cls, op_name in ((exp.Like, "LIKE"), (exp.ILike, "ILIKE")):
                for lk in where_node.find_all(like_cls):
                    if isinstance(lk.this, exp.Column):
                        t, c = _resolve_column_table(lk.this, aliases, default_tbl)
                        key = (canonical_table(t), c, op_name)
                        filter_counter[key] += 1
                        if isinstance(lk.expression, exp.Literal) and lk.expression.is_string:
                            if len(filter_values[key]) < 8:
                                filter_values[key].add(str(lk.expression.this))

            for btw in where_node.find_all(exp.Between):
                if isinstance(btw.this, exp.Column):
                    t, c = _resolve_column_table(btw.this, aliases, default_tbl)
                    key = (canonical_table(t), c, "BETWEEN")
                    filter_counter[key] += 1

        # 4. Expressões de agregação frequentes (candidatas a sql_snippets.measures)
        for agg in tree.find_all(exp.AggFunc):
            agg_sql = agg.sql(dialect="databricks")
            func_name = agg.sql_name().upper() if hasattr(agg, "sql_name") else agg.key.upper()
            agg_cols = list(agg.find_all(exp.Column))
            agg_tbl = None
            if agg_cols:
                t, _ = _resolve_column_table(agg_cols[0], aliases, default_tbl)
                agg_tbl = canonical_table(t) if t != "unknown" else None
            agg_counter[(agg_sql, func_name, agg_tbl)] += 1

    result.table_counts = dict(table_counter.most_common())
    result.column_counts = dict(col_counter.most_common())
    result.join_patterns = [
        JoinPattern(left_table=lt, right_table=rt, left_column=lc, right_column=rc, count=cnt)
        for (lt, rt, lc, rc), cnt in join_counter.most_common()
        if cnt >= min_occurrences
    ]
    result.filter_patterns = [
        FilterPattern(
            table=t,
            column=c,
            operator=op,
            count=cnt,
            sample_values=sorted(filter_values[(t, c, op)]),
        )
        for (t, c, op), cnt in filter_counter.most_common()
        if cnt >= min_occurrences
    ]
    result.aggregation_patterns = [
        AggregationPattern(expression_sql=expr_sql, function_name=fn, table=tbl, count=cnt)
        for (expr_sql, fn, tbl), cnt in agg_counter.most_common()
        if cnt >= min_occurrences
    ]
    return result
