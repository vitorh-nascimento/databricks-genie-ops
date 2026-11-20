"""Remapeamento multi-ambiente (catalog, schema e /Volumes/...) para promoção entre workspaces."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from genieops.models import EnvironmentConfig, SpaceBundle


@dataclass
class MigrationReport:
    """Resumo detalhado das substituições aplicadas na migração entre ambientes."""

    source_env: str
    target_env: str
    replacements: list[tuple[str, str]] = field(default_factory=list)
    surfaces_touched: dict[str, int] = field(default_factory=dict)


def _replace_identifier_prefix(text: str, old_prefix: str, new_prefix: str) -> tuple[str, int]:
    """Substitui prefixo de catálogo/schema respeitando limites de token e backticks."""
    if not text or not old_prefix or old_prefix == new_prefix:
        return text, 0

    # 1. Padrão com backticks: `old_cat`.`old_sch` ou `old_cat`
    escaped = re.escape(old_prefix)
    # Match word/backtick boundaries so 'analytics_dev' não corrompa 'analytics_dev_backup'
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])")
    new_text, count = pattern.subn(new_prefix, text)
    return new_text, count


def _replace_volume_path(
    text: str,
    src_cat: str | None,
    dst_cat: str | None,
    src_sch: str | None,
    dst_sch: str | None,
) -> tuple[str, int]:
    """Remapeia caminhos /Volumes/<catalog>/<schema>/... de forma segura."""
    if not text or "/Volumes/" not in text:
        return text, 0

    count = 0
    updated = text
    if src_cat and dst_cat and src_sch and dst_sch and (src_cat != dst_cat or src_sch != dst_sch):
        old_vp = f"/Volumes/{src_cat}/{src_sch}"
        new_vp = f"/Volumes/{dst_cat}/{dst_sch}"
        updated, c = _replace_identifier_prefix(updated, old_vp, new_vp)
        count += c
    elif src_cat and dst_cat and src_cat != dst_cat:
        old_vp = f"/Volumes/{src_cat}/"
        new_vp = f"/Volumes/{dst_cat}/"
        if old_vp in updated:
            count += updated.count(old_vp)
            updated = updated.replace(old_vp, new_vp)
    return updated, count


def _apply_sql_remap(
    text: str,
    src_env: EnvironmentConfig,
    dst_env: EnvironmentConfig,
) -> tuple[str, int]:
    """Aplica remapeamento de catalog.schema, catalog isolado e /Volumes/ em SQL/identificadores."""
    if not text:
        return text, 0

    total_changes = 0
    updated = text

    # Remapeamento de /Volumes/... primeiro (usa volume_catalog/volume_schema se definidos)
    v_src_cat = src_env.volume_catalog or src_env.catalog
    v_dst_cat = dst_env.volume_catalog or dst_env.catalog
    v_src_sch = src_env.volume_schema or src_env.schema_name
    v_dst_sch = dst_env.volume_schema or dst_env.schema_name
    updated, c = _replace_volume_path(updated, v_src_cat, v_dst_cat, v_src_sch, v_dst_sch)
    total_changes += c

    # Remapeamento composto catalog.schema (evita colisão quando schema também muda)
    if src_env.catalog and dst_env.catalog and src_env.schema_name and dst_env.schema_name:
        if src_env.catalog != dst_env.catalog or src_env.schema_name != dst_env.schema_name:
            old_cs = f"{src_env.catalog}.{src_env.schema_name}"
            new_cs = f"{dst_env.catalog}.{dst_env.schema_name}"
            updated, c = _replace_identifier_prefix(updated, old_cs, new_cs)
            total_changes += c

            old_cs_bt = f"`{src_env.catalog}`.`{src_env.schema_name}`"
            new_cs_bt = f"`{dst_env.catalog}`.`{dst_env.schema_name}`"
            if old_cs_bt in updated:
                total_changes += updated.count(old_cs_bt)
                updated = updated.replace(old_cs_bt, new_cs_bt)

    # Remapeamento de catalog remanescente (ex: outro schema no mesmo catalog)
    if src_env.catalog and dst_env.catalog and src_env.catalog != dst_env.catalog:
        updated, c = _replace_identifier_prefix(updated, src_env.catalog, dst_env.catalog)
        total_changes += c

    return updated, total_changes


def remap_space_bundle(
    bundle: SpaceBundle,
    source_env: EnvironmentConfig,
    target_env: EnvironmentConfig,
) -> tuple[SpaceBundle, MigrationReport]:
    """
    Clona o SpaceBundle remapeando catalog, schema e /Volumes/... em todas as superfícies:
    tables, metric_views, volumes, join_specs, sql_snippets, example_question_sqls,
    text_instructions e benchmarks.
    """
    cloned = bundle.model_copy(deep=True)
    report = MigrationReport(
        source_env=source_env.name or "source",
        target_env=target_env.name or "target",
    )

    if source_env.catalog and target_env.catalog and source_env.catalog != target_env.catalog:
        report.replacements.append((source_env.catalog, target_env.catalog))
    if (
        source_env.schema_name
        and target_env.schema_name
        and source_env.schema_name != target_env.schema_name
    ):
        report.replacements.append((source_env.schema_name, target_env.schema_name))

    def _bump(surface: str, count: int) -> None:
        if count > 0:
            report.surfaces_touched[surface] = report.surfaces_touched.get(surface, 0) + count

    # 1. Tables
    for tbl in cloned.sources.tables:
        tbl.identifier, c = _apply_sql_remap(tbl.identifier, source_env, target_env)
        _bump("tables", c)

    # 2. Metric Views
    for mv in cloned.sources.metric_views:
        mv.identifier, c = _apply_sql_remap(mv.identifier, source_env, target_env)
        _bump("metric_views", c)

    # 3. Volumes
    for vol in cloned.sources.volumes:
        vol.path, c = _apply_sql_remap(vol.path, source_env, target_env)
        _bump("volumes", c)

    # 4. Join Specs
    for js in cloned.instructions.join_specs:
        js.left.identifier, c1 = _apply_sql_remap(js.left.identifier, source_env, target_env)
        js.right.identifier, c2 = _apply_sql_remap(js.right.identifier, source_env, target_env)
        js.condition, c3 = _apply_sql_remap(js.condition, source_env, target_env)
        _bump("join_specs", c1 + c2 + c3)

    # 5. SQL Snippets
    for m in cloned.instructions.sql_snippets.measures:
        m.sql, c = _apply_sql_remap(m.sql, source_env, target_env)
        _bump("sql_snippets.measures", c)
    for f in cloned.instructions.sql_snippets.filters:
        f.sql, c = _apply_sql_remap(f.sql, source_env, target_env)
        _bump("sql_snippets.filters", c)
    for e in cloned.instructions.sql_snippets.expressions:
        e.sql, c = _apply_sql_remap(e.sql, source_env, target_env)
        _bump("sql_snippets.expressions", c)

    # 6. Example Question SQLs
    for ex in cloned.instructions.example_question_sqls:
        ex.sql, c = _apply_sql_remap(ex.sql, source_env, target_env)
        _bump("example_question_sqls", c)

    # 7. Text Instructions (caso mencione algum identificador)
    new_instructions: list[str] = []
    for line in cloned.instructions.text_instructions:
        remapped_line, c = _apply_sql_remap(line, source_env, target_env)
        _bump("text_instructions", c)
        new_instructions.append(remapped_line)
    cloned.instructions.text_instructions = new_instructions

    # 8. Benchmarks
    for bmk in cloned.benchmarks.questions:
        if bmk.ground_truth_sql:
            bmk.ground_truth_sql, c = _apply_sql_remap(
                bmk.ground_truth_sql, source_env, target_env
            )
            _bump("benchmarks", c)
        remapped_tables: list[str] = []
        for t in bmk.expected_tables:
            rt, c = _apply_sql_remap(t, source_env, target_env)
            _bump("benchmarks", c)
            remapped_tables.append(rt)
        bmk.expected_tables = remapped_tables

    return cloned, report
