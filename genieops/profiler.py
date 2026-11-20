"""Data Profiling & Auto-Curadoria Assistida (100% read-only via Databricks CLI / SQL Warehouse)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from genieops.ast_profiler import ASTProfileResult, analyze_query_history_ast
from genieops.databricks_client import DatabricksClient
from genieops.models import SpaceBundle

TECHNICAL_COL_RE = re.compile(
    r"(^_|\b_ts$|\b_at$|\b_em$|^id_|_id$|^sk_|^pk_|hash|uuid|guid|batch_id|load_date|ingestion|etl_|staging)",
    re.IGNORECASE,
)
DATE_COL_RE = re.compile(r"(data|date|dt_|_dt$|competencia|mes|month|timestamp|_ts$|_at$)", re.IGNORECASE)


@dataclass
class CurationSuggestion:
    table: str
    column: str | None
    category: str  # ENTITY_MATCHING | EXCLUDE_CANDIDATE | MISSING_DESCRIPTION | AMBIGUOUS_DATES | JOIN_OR_MV_HINT
    reason: str
    suggested_yaml: str


@dataclass
class ProfileReport:
    space_name: str
    env: str
    tables_profiled: int = 0
    suggestions: list[CurationSuggestion] = field(default_factory=list)
    query_history_samples: int = 0
    ast_profile: ASTProfileResult | None = None
    warnings: list[str] = field(default_factory=list)


def _extract_columns_from_schema(schema_payload: Any, identifier: str) -> list[dict[str, Any]]:
    """Extrai metadados de colunas do retorno de `discover-schema`."""
    if isinstance(schema_payload, dict):
        if "tables" in schema_payload:
            for t in schema_payload["tables"]:
                if t.get("identifier") == identifier or t.get("full_name") == identifier:
                    return t.get("columns", [])
        if "columns" in schema_payload:
            return schema_payload["columns"]
    if isinstance(schema_payload, list):
        for item in schema_payload:
            if isinstance(item, dict) and (
                item.get("identifier") == identifier
                or item.get("full_name") == identifier
                or item.get("table") == identifier
            ):
                return item.get("columns", [])
        if schema_payload and isinstance(schema_payload[0], dict) and "name" in schema_payload[0]:
            return schema_payload
    return []


def profile_space(
    bundle: SpaceBundle,
    client: DatabricksClient,
    env_name: str = "dev",
    warehouse_id: str | None = None,
    include_query_history: bool = False,
) -> ProfileReport:
    """
    Executa profiling estritamente read-only das tabelas/Metric Views do Space e gera
    sugestões acionáveis de curadoria (entity_matching, exclude, descrições, datas ambíguas e joins).
    """
    report = ProfileReport(space_name=bundle.space.name, env=env_name)
    all_sources = list(bundle.sources.tables) + list(bundle.sources.metric_views)
    if not all_sources:
        report.warnings.append("Nenhuma tabela ou Metric View encontrada em sources.yaml para profiling.")
        return report

    identifiers = [s.identifier for s in all_sources]
    try:
        schema_data = client.discover_schema(identifiers)
    except Exception as exc:
        report.warnings.append(f"Não foi possível executar discover-schema: {exc}")
        schema_data = {}

    table_pk_candidates: dict[str, set[str]] = {}

    for src in all_sources:
        report.tables_profiled += 1
        existing_cols = {c.column_name.lower(): c for c in src.column_configs}
        discovered_cols = _extract_columns_from_schema(schema_data, src.identifier)

        # Fallback read-only via DESCRIBE TABLE se discover-schema não trouxer colunas
        if not discovered_cols:
            try:
                qres = client.execute_readonly_sql(
                    f"DESCRIBE TABLE {src.identifier}", warehouse_id=warehouse_id
                )
                for row in qres.rows:
                    if row and row[0] and not str(row[0]).startswith("#"):
                        discovered_cols.append(
                            {
                                "name": str(row[0]),
                                "type": str(row[1]) if len(row) > 1 else "string",
                                "comment": str(row[2]) if len(row) > 2 and row[2] else "",
                            }
                        )
            except Exception as exc:
                report.warnings.append(f"Falha ao executar DESCRIBE em {src.identifier}: {exc}")
                continue

        date_cols: list[str] = []
        id_cols: set[str] = set()

        for col in discovered_cols:
            cname = str(col.get("name") or col.get("column_name") or "").strip()
            if not cname:
                continue
            ctype = str(col.get("type") or col.get("data_type") or "").lower()
            comment = str(col.get("comment") or col.get("description") or "").strip()
            distinct_count = col.get("distinct_count") or col.get("approx_distinct")
            null_ratio = col.get("null_ratio")
            existing = existing_cols.get(cname.lower())

            if DATE_COL_RE.search(cname) or "date" in ctype or "timestamp" in ctype:
                date_cols.append(cname)
            if cname.lower().startswith("id_") or cname.lower().endswith("_id"):
                id_cols.add(cname.lower())

            # 1. Candidato a exclude: true
            if (
                TECHNICAL_COL_RE.search(cname)
                and not (existing and existing.exclude)
                and (null_ratio is None or float(null_ratio) >= 0.0)
            ):
                report.suggestions.append(
                    CurationSuggestion(
                        table=src.identifier,
                        column=cname,
                        category="EXCLUDE_CANDIDATE",
                        reason=f"Coluna técnica/identificador interno ('{cname}', tipo={ctype}) pode poluir o contexto do Genie.",
                        suggested_yaml=f"- column_name: {cname}\n  exclude: true",
                    )
                )
                continue

            if null_ratio is not None and float(null_ratio) >= 0.95 and not (existing and existing.exclude):
                report.suggestions.append(
                    CurationSuggestion(
                        table=src.identifier,
                        column=cname,
                        category="EXCLUDE_CANDIDATE",
                        reason=f"Coluna com {float(null_ratio) * 100:.1f}% de valores nulos.",
                        suggested_yaml=f"- column_name: {cname}\n  exclude: true",
                    )
                )
                continue

            # 2. Candidato a enable_entity_matching + enable_format_assistance
            is_string_type = any(t in ctype for t in ("string", "varchar", "char"))
            low_med_card = distinct_count is not None and 2 <= int(distinct_count) <= 200
            if is_string_type and low_med_card and not (existing and existing.enable_entity_matching):
                report.suggestions.append(
                    CurationSuggestion(
                        table=src.identifier,
                        column=cname,
                        category="ENTITY_MATCHING",
                        reason=f"Coluna categórica string com baixa/média cardinalidade ({distinct_count} valores distintos).",
                        suggested_yaml=(
                            f"- column_name: {cname}\n"
                            f"  enable_entity_matching: true\n"
                            f"  enable_format_assistance: true"
                        ),
                    )
                )

            # 3. Coluna sem descrição tanto no UC quanto no sources.yaml
            if not comment and not (existing and existing.description):
                report.suggestions.append(
                    CurationSuggestion(
                        table=src.identifier,
                        column=cname,
                        category="MISSING_DESCRIPTION",
                        reason=f"Coluna '{cname}' sem comentário no Unity Catalog nem descrição em column_configs.",
                        suggested_yaml=f"- column_name: {cname}\n  description:\n    - \"<Descreva o significado de negócio de {cname}>\"",
                    )
                )

        # 4. Múltiplas colunas de data sem papel claro
        if len(date_cols) >= 2:
            undocumented_dates = [
                d for d in date_cols if not (existing_cols.get(d.lower()) and existing_cols[d.lower()].description)
            ]
            if undocumented_dates:
                report.suggestions.append(
                    CurationSuggestion(
                        table=src.identifier,
                        column=", ".join(date_cols),
                        category="AMBIGUOUS_DATES",
                        reason=f"Múltiplas colunas temporais encontradas ({', '.join(date_cols)}) sem papel semântico documentado em todas.",
                        suggested_yaml="# Documente claramente qual data representa evento vs faturamento/competência.",
                    )
                )

        table_pk_candidates[src.identifier] = id_cols

    # 5. Candidatos a Join Specs (chaves compartilhadas entre tabelas sem join_spec declarado)
    existing_join_pairs = {
        frozenset((js.left.identifier, js.right.identifier))
        for js in bundle.instructions.join_specs
    }
    table_ids = list(table_pk_candidates.keys())
    for i in range(len(table_ids)):
        for j in range(i + 1, len(table_ids)):
            t1, t2 = table_ids[i], table_ids[j]
            if frozenset((t1, t2)) in existing_join_pairs:
                continue
            shared_keys = sorted(table_pk_candidates[t1] & table_pk_candidates[t2])
            if shared_keys:
                a1, a2 = t1.split(".")[-1], t2.split(".")[-1]
                key = shared_keys[0]
                report.suggestions.append(
                    CurationSuggestion(
                        table=f"{t1} <-> {t2}",
                        column=key,
                        category="JOIN_OR_MV_HINT",
                        reason=f"Chave compartilhada '{key}' detectada entre tabelas sem join_spec declarado (validar grão PK/FK nos dados antes de aplicar).",
                        suggested_yaml=(
                            f"- left: {{identifier: {t1}, alias: {a1}}}\n"
                            f"  right: {{identifier: {t2}, alias: {a2}}}\n"
                            f"  condition: \"`{a1}`.`{key}` = `{a2}`.`{key}`\"\n"
                            f"  relationship_type: MANY_TO_ONE"
                        ),
                    )
                )

    # 6. Opcional: consulta read-only em system.query.history com parsing AST (sqlglot)
    if include_query_history and all_sources:
        short_names = [s.identifier.split(".")[-1] for s in all_sources]
        like_clauses = " OR ".join(
            f"statement_text ILIKE '%{re.sub(r'[^A-Za-z0-9_]', '', sn)}%'"
            for sn in short_names
            if re.sub(r"[^A-Za-z0-9_]", "", sn)
        )
        if like_clauses:
            try:
                qh = client.execute_readonly_sql(
                    f"SELECT statement_text FROM system.query.history "
                    f"WHERE statement_type = 'SELECT' AND ({like_clauses}) "
                    f"AND end_time > current_timestamp() - INTERVAL 30 DAYS "
                    f"ORDER BY end_time DESC LIMIT 100",
                    warehouse_id=warehouse_id,
                )
                sql_samples = [str(row[0]) for row in qh.rows if row and row[0]]
                report.query_history_samples = len(sql_samples)

                if sql_samples:
                    ast_res = analyze_query_history_ast(
                        sql_samples,
                        known_tables=[s.identifier for s in all_sources],
                        min_occurrences=1,
                    )
                    report.ast_profile = ast_res

                    # Sugestões de Join Specs descobertos no AST
                    for jp in ast_res.join_patterns[:5]:
                        if frozenset((jp.left_table, jp.right_table)) in existing_join_pairs:
                            continue
                        a1, a2 = jp.left_table.split(".")[-1], jp.right_table.split(".")[-1]
                        report.suggestions.append(
                            CurationSuggestion(
                                table=f"{jp.left_table} <-> {jp.right_table}",
                                column=f"{jp.left_column} = {jp.right_column}",
                                category="JOIN_OR_MV_HINT",
                                reason=(
                                    f"AST query.history: JOIN observado {jp.count}x "
                                    f"({a1}.{jp.left_column} = {a2}.{jp.right_column})."
                                ),
                                suggested_yaml=(
                                    f"- left: {{identifier: {jp.left_table}, alias: {a1}}}\n"
                                    f"  right: {{identifier: {jp.right_table}, alias: {a2}}}\n"
                                    f"  condition: \"`{a1}`.`{jp.left_column}` = `{a2}`.`{jp.right_column}`\"\n"
                                    f"  relationship_type: MANY_TO_ONE"
                                ),
                            )
                        )

                    # Sugestões de Filtros frequentes descobertos no AST
                    for fp in ast_res.filter_patterns[:6]:
                        short_t = fp.table.split(".")[-1]
                        samples_txt = (
                            f" Valores observados: {', '.join(fp.sample_values[:4])}."
                            if fp.sample_values
                            else ""
                        )
                        if fp.sample_values:
                            first_val = fp.sample_values[0].replace("'", "''")
                            snippet_sql = f"`{short_t}`.`{fp.column}` = '{first_val}'"
                        else:
                            snippet_sql = f"`{short_t}`.`{fp.column}` {fp.operator} <valor>"
                        report.suggestions.append(
                            CurationSuggestion(
                                table=fp.table,
                                column=fp.column,
                                category="FILTER_SNIPPET_HINT",
                                reason=(
                                    f"AST query.history: filtro '{fp.operator}' frequente ({fp.count}x) "
                                    f"em {short_t}.{fp.column}.{samples_txt}"
                                ),
                                suggested_yaml=(
                                    f"# Avalie enable_entity_matching ou sql_snippets.filters:\n"
                                    f"- display_name: \"Filtro {fp.column}\"\n"
                                    f"  sql: \"{snippet_sql}\""
                                ),
                            )
                        )

                    # Sugestões de Medidas/Agregações frequentes descobertas no AST
                    for ap in ast_res.aggregation_patterns[:5]:
                        if ap.count < 2:
                            continue
                        alias_base = re.sub(r"[^a-z0-9_]", "_", ap.function_name.lower())
                        report.suggestions.append(
                            CurationSuggestion(
                                table=ap.table or all_sources[0].identifier,
                                column=None,
                                category="MEASURE_SNIPPET_HINT",
                                reason=(
                                    f"AST query.history: agregação `{ap.expression_sql}` "
                                    f"observada {ap.count}x — candidata a medida governada/snippet."
                                ),
                                suggested_yaml=(
                                    f"- alias: {alias_base}_recorrente\n"
                                    f"  display_name: \"Medida {ap.function_name}\"\n"
                                    f"  sql: \"{ap.expression_sql}\""
                                ),
                            )
                        )
            except Exception as exc:
                report.warnings.append(f"system.query.history indisponível ou sem permissão: {exc}")

    return report
