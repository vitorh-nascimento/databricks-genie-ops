"""Testes para SQL Functions (Trusted Assets), paráfrases, rótulos de rodada, COMMENTs UC e Star Schema Kit."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from genieops.benchmark import run_benchmark
from genieops.cli import app
from genieops.compiler import compile_space, diff_payloads
from genieops.curation_kit import generate_star_schema_kit, generate_uc_comments_sql
from genieops.docs_generator import generate_docs
from genieops.history import HistoryStore
from genieops.linter import lint_space
from genieops.models import ExampleQuestionSql, SpaceBundle, SqlFunction
from genieops.uc_export import build_uc_export_plan
from tests.conftest import REPO_ROOT


def test_sql_functions_lint_compile_and_diff(exemplo_bundle: SpaceBundle) -> None:
    compiled = compile_space(exemplo_bundle)
    fns = compiled["instructions"]["sql_functions"]
    assert len(fns) == 3
    assert fns == sorted(fns, key=lambda x: (x["id"], x["identifier"]))

    # Diff detecta alteração em sql_functions
    mutated = exemplo_bundle.model_copy(deep=True)
    mutated.instructions.sql_functions.append(
        SqlFunction(identifier="analytics_dev.sales_gold.fn_nova_regra")
    )
    diff = diff_payloads(compile_space(mutated), compiled)
    assert diff.has_changes is True
    assert any("sql_functions" in s for s in diff.summary)

    # Linter bloqueia identificador fora do padrão 3 partes e avisa duplicata
    bad = exemplo_bundle.model_copy(deep=True)
    bad.instructions.sql_functions.append(SqlFunction(identifier="fn_sem_catalog"))
    bad.instructions.sql_functions.append(
        SqlFunction(identifier=exemplo_bundle.instructions.sql_functions[0].identifier)
    )
    rep = lint_space(bad)
    assert any(i.code == "SQLF001" and i.severity == "ERROR" for i in rep.issues)
    assert any(i.code == "SQLF001" and i.severity == "WARNING" for i in rep.issues)


def test_paraphrases_expansion_leakage_and_round_labels(
    exemplo_bundle: SpaceBundle, tmp_path: Path
) -> None:
    # 1. Compilação com expansão de paráfrases gera 32 + 64 = 96 perguntas únicas
    expanded_payload = compile_space(exemplo_bundle, expand_paraphrases=True)
    qs = expanded_payload["benchmarks"]["questions"]
    assert len(qs) == 96
    assert len({q["id"] for q in qs}) == 96

    # 2. Linter detecta Benchmark Leakage mesmo copiando uma paráfrase
    leaked = exemplo_bundle.model_copy(deep=True)
    leaked.instructions.example_question_sqls.append(
        ExampleQuestionSql(
            question=leaked.benchmarks.questions[0].paraphrases[0],
            sql="SELECT 1",
        )
    )
    rep = lint_space(leaked)
    assert any(i.code == "LEAK001" and i.severity == "ERROR" for i in rep.issues)

    # 3. Rodadas rotuladas em SQLite + evolução na documentação + exportação Delta
    history = HistoryStore(db_path=tmp_path / "history.db")
    broken = exemplo_bundle.model_copy(deep=True)
    broken.benchmarks.questions[0].expected_tables = ["tabela_inexistente"]

    run0, _ = run_benchmark(
        broken,
        env_name="dev",
        mode="offline",
        history=history,
        label="Rodada 0 - Só tabelas",
    )
    run1, diff1 = run_benchmark(
        exemplo_bundle,
        env_name="dev",
        mode="offline",
        history=history,
        label="Rodada 1 - Curadoria Completa",
        expand_paraphrases=True,
    )

    assert run0.label == "Rodada 0 - Só tabelas"
    assert run1.label == "Rodada 1 - Curadoria Completa"
    assert run1.total == 96
    assert run1.accuracy_pct == 100.0
    assert diff1 is not None and diff1.delta_accuracy > 0

    # Docs incluem tabela de evolução da acurácia com os rótulos das rodadas
    docs = generate_docs(exemplo_bundle, output_dir=tmp_path / "docs", history=history)
    rel_md = docs["relatorio_executivo_md"].read_text(encoding="utf-8")
    rel_html = docs["relatorio_executivo_html"].read_text(encoding="utf-8")
    spec_md = docs["spec_tecnica"].read_text(encoding="utf-8")
    assert "Rodada 0 - Só tabelas" in rel_md
    assert "Rodada 1 - Curadoria Completa" in rel_md
    assert "Evolução da Acurácia por Rodada" in rel_html
    assert "fn_receita_liquida_periodo" in spec_md

    # Exportação Delta preserva os rótulos das rodadas
    plan = build_uc_export_plan(
        exemplo_bundle,
        history,
        catalog="analytics_ops",
        schema="genieops_audit",
        schema_mode="four_tables",
    )
    sql_four = plan.full_sql()
    assert "Rodada 0 - Só tabelas" in sql_four
    assert "Rodada 1 - Curadoria Completa" in sql_four


def test_history_store_migrates_legacy_db_without_label_column(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE benchmark_runs (
                run_id TEXT PRIMARY KEY,
                space_name TEXT NOT NULL,
                env TEXT NOT NULL,
                mode TEXT NOT NULL,
                created_at TEXT NOT NULL,
                total INTEGER NOT NULL,
                passed INTEGER NOT NULL,
                failed INTEGER NOT NULL,
                needs_review INTEGER NOT NULL,
                excluded INTEGER NOT NULL,
                accuracy_pct REAL NOT NULL,
                avg_latency_ms REAL NOT NULL,
                p50_latency_ms REAL NOT NULL,
                p95_latency_ms REAL NOT NULL,
                config_hash TEXT NOT NULL
            )
            """
        )

    store = HistoryStore(db_path=db_path)
    with sqlite3.connect(store.db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(benchmark_runs)").fetchall()}
    assert "label" in cols


def test_curation_kit_uc_comments_and_star_schema_cli(
    exemplo_bundle: SpaceBundle, tmp_path: Path, monkeypatch
) -> None:
    # 1. UC COMMENTs SQL
    comments_sql = generate_uc_comments_sql(exemplo_bundle)
    assert "COMMENT ON TABLE analytics_dev.sales_gold.fct_pedidos IS" in comments_sql
    assert "ALTER TABLE analytics_dev.sales_gold.fct_pedidos ALTER COLUMN `valor_liquido` COMMENT" in comments_sql
    assert "Sinônimos de negócio:" in comments_sql

    # 2. Star Schema Kit completo
    kit_dir = tmp_path / "kit_vendas"
    outputs = generate_star_schema_kit(
        catalog="analytics_dev",
        schema="sales_gold",
        output_dir=kit_dir,
        bundle=exemplo_bundle,
    )
    assert set(outputs.keys()) == {"seed_script", "uc_comments", "trusted_sql_functions", "playbook"}
    for p in outputs.values():
        assert p.exists() and p.stat().st_size > 200

    seed_txt = outputs["seed_script"].read_text(encoding="utf-8")
    assert "dim_clientes" in seed_txt and "fct_pedidos" in seed_txt
    assert "competencia_faturamento" in seed_txt

    udf_txt = outputs["trusted_sql_functions"].read_text(encoding="utf-8")
    assert "CREATE OR REPLACE FUNCTION analytics_dev.sales_gold.fn_receita_liquida_periodo" in udf_txt
    assert "CREATE OR REPLACE FUNCTION analytics_dev.sales_gold.fn_taxa_cancelamento_regiao" in udf_txt
    assert "CREATE OR REPLACE FUNCTION analytics_dev.sales_gold.fn_top_clientes_segmento" in udf_txt

    # 3. CLI commands uc-comments e seed-star-schema
    monkeypatch.chdir(REPO_ROOT)
    cli_runner = CliRunner()

    out_sql = tmp_path / "comments_prod.sql"
    r_uc = cli_runner.invoke(
        app,
        ["uc-comments", "exemplo_vendas", "--env", "prod", "--output", str(out_sql)],
    )
    assert r_uc.exit_code == 0
    assert out_sql.exists()
    assert "analytics_prod.sales_gold.fct_pedidos" in out_sql.read_text(encoding="utf-8")

    cli_kit_dir = tmp_path / "cli_kit"
    r_seed = cli_runner.invoke(
        app,
        [
            "seed-star-schema",
            "--catalog",
            "analytics_dev",
            "--schema",
            "sales_gold",
            "--output-dir",
            str(cli_kit_dir),
        ],
    )
    assert r_seed.exit_code == 0
    assert (cli_kit_dir / "01_seed_star_schema.py").exists()
    assert (cli_kit_dir / "GUIA_RODADAS_CURADORIA.md").exists()
