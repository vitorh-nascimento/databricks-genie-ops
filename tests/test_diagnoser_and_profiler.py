"""Testes do Diagnosticador, Data Profiler read-only e Feedback Harvester."""

from __future__ import annotations

from pathlib import Path

import yaml

from genieops.diagnoser import diagnose_run
from genieops.harvester import harvest_feedback
from genieops.history import BenchmarkItemResult, BenchmarkRunRecord
from genieops.models import SpaceBundle
from genieops.profiler import profile_space
from tests.conftest import FakeCompletedProcess, make_json_response


def test_diagnoser_classifies_root_causes_and_respects_hierarchy(exemplo_bundle: SpaceBundle) -> None:
    run = BenchmarkRunRecord(
        run_id="run_diag_1",
        space_name=exemplo_bundle.space.name,
        env="dev",
        mode="live",
        created_at="2026-11-20T12:00:00Z",
        total=4,
        passed=0,
        failed=4,
        needs_review=0,
        excluded=0,
        accuracy_pct=0.0,
        avg_latency_ms=1200.0,
        p50_latency_ms=1100.0,
        p95_latency_ms=1500.0,
        config_hash="abc123",
        items=[
            BenchmarkItemResult(
                case_id="c1",
                question="Receita por região na Metric View",
                domain="KPIs",
                difficulty="medium",
                mode="chat",
                status="BAD",
                semantic_score=0.0,
                expected_sql="SELECT regiao, MEASURE(receita_liquida_total) FROM mv_kpis_comerciais GROUP BY ALL",
                generated_sql="SELECT regiao, SUM(receita_liquida_total) FROM mv_kpis_comerciais GROUP BY regiao",
            ),
            BenchmarkItemResult(
                case_id="c2",
                question="Pedidos cancelados",
                domain="Ops",
                difficulty="easy",
                mode="chat",
                status="BAD",
                semantic_score=0.0,
                expected_sql="SELECT COUNT(*) FROM fct_pedidos WHERE status_pedido = 'Cancelado'",
                generated_sql="SELECT COUNT(*) FROM fct_pedidos WHERE status_pedido = 'CANCELLED'",
            ),
            BenchmarkItemResult(
                case_id="c3",
                question="Top clientes",
                domain="Clientes",
                difficulty="medium",
                mode="chat",
                status="BAD",
                semantic_score=0.0,
                expected_sql="SELECT c.nome_cliente, SUM(p.valor_liquido) FROM fct_pedidos p JOIN dim_clientes c ON p.id_cliente = c.id_cliente GROUP BY c.nome_cliente",
                generated_sql="SELECT id_cliente, SUM(valor_liquido) FROM fct_pedidos GROUP BY id_cliente",
            ),
            BenchmarkItemResult(
                case_id="c4",
                question="Erro de permissão",
                domain="Infra",
                difficulty="easy",
                mode="chat",
                status="BAD",
                semantic_score=0.0,
                expected_sql="SELECT 1",
                generated_sql=None,
                error_message="[INSUFFICIENT_PERMISSIONS] User does not have SELECT",
            ),
        ],
    )

    report = diagnose_run(run, exemplo_bundle)
    assert report.total_failures == 4
    by_id = {d.case_id: d for d in report.diagnoses}
    assert by_id["c1"].root_cause_class == "Wrong Metric View measure"
    assert by_id["c2"].root_cause_class == "Wrong filter value"
    assert "Entity Matching" in by_id["c2"].recommended_lever
    assert by_id["c3"].root_cause_class == "Wrong join / grain"
    assert by_id["c4"].root_cause_class == "Infra / permission / execution error"


def test_profiler_generates_curation_suggestions_readonly(
    exemplo_bundle: SpaceBundle, mock_client_factory
) -> None:
    def handler(cmd: list[str]) -> FakeCompletedProcess:
        if "discover-schema" in cmd:
            return make_json_response(
                [
                    {
                        "identifier": "analytics_dev.sales_gold.fct_pedidos",
                        "columns": [
                            {"name": "etl_batch_hash", "type": "string", "distinct_count": 50000},
                            {"name": "motivo_cancelamento", "type": "string", "distinct_count": 12, "comment": ""},
                            {"name": "data_entrega", "type": "date", "comment": ""},
                            {"name": "data_faturamento", "type": "date", "comment": ""},
                        ],
                    },
                    {
                        "identifier": "analytics_dev.sales_gold.dim_clientes",
                        "columns": [
                            {"name": "id_cliente", "type": "string"},
                            {"name": "classificacao_risco", "type": "string", "distinct_count": 4, "comment": ""},
                        ],
                    },
                ]
            )
        return make_json_response({"columns": [], "rows": []})

    client, _ = mock_client_factory(handler)
    rep = profile_space(exemplo_bundle, client=client, env_name="dev")
    categories = {s.category for s in rep.suggestions}
    assert "EXCLUDE_CANDIDATE" in categories
    assert "ENTITY_MATCHING" in categories
    assert "MISSING_DESCRIPTION" in categories
    assert "AMBIGUOUS_DATES" in categories


def test_harvest_feedback_exports_yaml_draft(tmp_path: Path, mock_client_factory) -> None:
    def handler(cmd: list[str]) -> FakeCompletedProcess:
        if "list-conversations" in cmd:
            return make_json_response({"conversations": [{"conversation_id": "conv_10"}]})
        if "list-conversation-messages" in cmd:
            return make_json_response(
                {
                    "messages": [
                        {
                            "message_id": "m1",
                            "content": "Qual a receita líquida por gerente regional?",
                            "status": "COMPLETED",
                            "feedback": {"rating": "NEGATIVE"},
                            "attachments": [{"query": {"query": "SELECT * FROM fct_pedidos"}}],
                        },
                        {
                            "message_id": "m2",
                            "content": "Total de pedidos em 2026-01",
                            "status": "COMPLETED",
                            "feedback": {"rating": "POSITIVE"},
                        },
                        {
                            "message_id": "m3",
                            "content": "Qual o churn líquido trimestral?",
                            "status": "FAILED",
                            "error": {"error": "SQL_EXECUTION_EXCEPTION"},
                        },
                    ]
                }
            )
        return make_json_response({})

    client, _ = mock_client_factory(handler)
    draft_file = tmp_path / "benchmarks_draft.yaml"
    rep = harvest_feedback("exemplo_vendas", space_id="sp_prod", client=client, output_path=draft_file)
    assert rep.conversations_scanned == 1
    assert len(rep.candidates) == 2
    assert draft_file.exists()

    parsed = yaml.safe_load(draft_file.read_text(encoding="utf-8"))
    assert len(parsed["questions"]) == 2
    assert parsed["questions"][0]["question"] == "Qual a receita líquida por gerente regional?"
