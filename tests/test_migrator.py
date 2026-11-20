"""Testes de migração multi-ambiente (catalog, schema e /Volumes/...) em todas as superfícies."""

from __future__ import annotations

from genieops.compiler import compile_space
from genieops.migrator import remap_space_bundle
from genieops.models import EnvironmentConfig, SpaceBundle


def test_migrate_remaps_all_surfaces(exemplo_bundle: SpaceBundle) -> None:
    src_env = EnvironmentConfig(
        name="dev",
        catalog="analytics_dev",
        schema="sales_gold",
        volume_catalog="analytics_dev",
        volume_schema="sales_docs",
    )
    dst_env = EnvironmentConfig(
        name="prod",
        catalog="analytics_prod",
        schema="commercial_gold",
        volume_catalog="analytics_prod",
        volume_schema="commercial_docs",
    )

    remapped, report = remap_space_bundle(exemplo_bundle, src_env, dst_env)

    # Tables & Metric Views
    for tbl in remapped.sources.tables:
        assert tbl.identifier.startswith("analytics_prod.commercial_gold.")
        assert "analytics_dev" not in tbl.identifier
    for mv in remapped.sources.metric_views:
        assert mv.identifier == "analytics_prod.commercial_gold.mv_kpis_comerciais"

    # Volumes
    assert remapped.sources.volumes[0].path == "/Volumes/analytics_prod/commercial_docs/politicas_comerciais"

    # Join Specs
    js = remapped.instructions.join_specs[0]
    assert js.left.identifier == "analytics_prod.commercial_gold.fct_pedidos"
    assert js.right.identifier == "analytics_prod.commercial_gold.dim_clientes"

    # Example SQLs & Benchmarks
    for ex in remapped.instructions.example_question_sqls:
        assert "analytics_dev" not in ex.sql
        assert "analytics_prod.commercial_gold." in ex.sql

    chat_bmks = [b for b in remapped.benchmarks.questions if b.ground_truth_sql]
    assert len(chat_bmks) == 20
    for b in chat_bmks:
        assert "analytics_dev" not in (b.ground_truth_sql or "")
        assert "analytics_prod.commercial_gold." in (b.ground_truth_sql or "")

    # Relatório deve listar superfícies tocadas
    assert report.surfaces_touched["tables"] >= 2
    assert report.surfaces_touched["metric_views"] >= 1
    assert report.surfaces_touched["volumes"] >= 1
    assert report.surfaces_touched["join_specs"] >= 2
    assert report.surfaces_touched["example_question_sqls"] >= 3
    assert report.surfaces_touched["benchmarks"] >= 20

    # Compilação após migração continua válida e sem vestígios do ambiente origem
    compiled_json = str(compile_space(remapped))
    assert "analytics_dev" not in compiled_json
    assert "sales_docs" not in compiled_json
