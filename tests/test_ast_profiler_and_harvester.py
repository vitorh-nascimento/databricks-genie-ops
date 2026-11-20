"""Testes unitários do AST Profiler (sqlglot/query.history) e Harvester (audit + deduplicação semântica)."""

from __future__ import annotations

import json
from pathlib import Path

from genieops.ast_profiler import analyze_query_history_ast
from genieops.harvester import harvest_feedback, semantic_similarity
from genieops.profiler import profile_space
from tests.conftest import make_json_response


def test_ast_profiler_extracts_joins_filters_and_aggregations():
    queries = [
        """
        SELECT c.segmento, SUM(p.valor_liquido) AS receita
        FROM analytics_dev.comercial_gold.fct_pedidos p
        JOIN analytics_dev.comercial_gold.dim_clientes c
          ON p.id_cliente = c.id_cliente
        WHERE p.status_pedido = 'FATURADO'
          AND c.regiao IN ('Sudeste', 'Sul')
        GROUP BY c.segmento
        """,
        """
        SELECT p.canal_venda, SUM(p.valor_liquido) AS total_vendas, COUNT(DISTINCT p.id_cliente) AS clientes
        FROM analytics_dev.comercial_gold.fct_pedidos p
        JOIN analytics_dev.comercial_gold.dim_clientes c
          ON p.id_cliente = c.id_cliente
        WHERE p.status_pedido = 'FATURADO'
        GROUP BY p.canal_venda
        """,
        "SELECT ??? INVALID SQL NOT PARSEABLE (((",
    ]
    res = analyze_query_history_ast(
        queries,
        known_tables=[
            "analytics_dev.comercial_gold.fct_pedidos",
            "analytics_dev.comercial_gold.dim_clientes",
        ],
    )

    assert res.queries_parsed == 2
    assert res.queries_failed == 1
    assert len(res.join_patterns) == 1
    jp = res.join_patterns[0]
    assert jp.count == 2
    assert {jp.left_column, jp.right_column} == {"id_cliente"}

    status_filter = next(
        (f for f in res.filter_patterns if f.column == "status_pedido" and f.operator == "="),
        None,
    )
    assert status_filter is not None
    assert status_filter.count == 2
    assert "FATURADO" in status_filter.sample_values

    regiao_filter = next(
        (f for f in res.filter_patterns if f.column == "regiao" and f.operator == "IN"),
        None,
    )
    assert regiao_filter is not None
    assert "Sudeste" in regiao_filter.sample_values

    sum_agg = next((a for a in res.aggregation_patterns if a.function_name == "SUM"), None)
    assert sum_agg is not None
    assert sum_agg.count == 2


def test_profile_space_with_ast_query_history(exemplo_bundle, mock_client_factory):
    def handler(cmd: list[str]):
        joined = " ".join(cmd)
        if "discover-schema" in joined:
            return make_json_response(
                {
                    "tables": [
                        {
                            "identifier": "analytics_dev.comercial_gold.fct_pedidos",
                            "columns": [
                                {"name": "status_pedido", "type": "string", "distinct_count": 4},
                                {"name": "valor_liquido", "type": "decimal(18,2)"},
                            ],
                        }
                    ]
                }
            )
        if "system.query.history" in joined:
            return make_json_response(
                {
                    "columns": ["statement_text"],
                    "rows": [
                        [
                            "SELECT p.canal_venda, SUM(p.valor_liquido) "
                            "FROM analytics_dev.comercial_gold.fct_pedidos p "
                            "WHERE p.status_pedido = 'FATURADO' GROUP BY p.canal_venda"
                        ],
                        [
                            "SELECT p.regiao, SUM(p.valor_liquido) "
                            "FROM analytics_dev.comercial_gold.fct_pedidos p "
                            "WHERE p.status_pedido = 'FATURADO' GROUP BY p.regiao"
                        ],
                    ],
                }
            )
        return make_json_response({})

    client, _ = mock_client_factory(handler)
    rep = profile_space(exemplo_bundle, client=client, env_name="dev", include_query_history=True)

    assert rep.query_history_samples == 2
    assert rep.ast_profile is not None
    assert rep.ast_profile.queries_parsed == 2
    categories = {s.category for s in rep.suggestions}
    assert "FILTER_SNIPPET_HINT" in categories
    assert "MEASURE_SNIPPET_HINT" in categories


def test_harvester_semantic_dedup_and_audit_log(tmp_path: Path, mock_client_factory):
    assert semantic_similarity(
        "Qual foi a receita liquida por regiao em 2026?",
        "Qual a receita liquida por regiao em 2026?",
    ) >= 0.78

    def handler(cmd: list[str]):
        joined = " ".join(cmd)
        if "list-conversations" in joined:
            return make_json_response({"conversations": [{"conversation_id": "conv_1"}]})
        if "list-conversation-messages" in joined:
            return make_json_response(
                {
                    "messages": [
                        {
                            "message_id": "m1",
                            "content": "Qual foi a receita liquida por regiao em 2026?",
                            "status": "COMPLETED",
                            "feedback": {"rating": "NEGATIVE"},
                        },
                        {
                            "message_id": "m2",
                            "content": "Qual a receita liquida por regiao em 2026?",
                            "status": "FAILED",
                            "error": {"error": "SQL timeout"},
                        },
                        {
                            "message_id": "m3",
                            "content": "Pergunta ja coberta no benchmark oficial",
                            "status": "FAILED",
                        },
                    ]
                }
            )
        if "system.access.audit" in joined:
            return make_json_response(
                {
                    "columns": ["event_time", "action_name", "request_params"],
                    "rows": [
                        [
                            "2026-11-19T12:00:00Z",
                            "updateConversationMessageFeedback",
                            json.dumps(
                                {
                                    "space_id": "sp_prod_01",
                                    "rating": "NEGATIVE",
                                    "question": "Qual o churn mensal de clientes enterprise?",
                                    "conversation_id": "conv_audit_9",
                                    "message_id": "msg_audit_9",
                                }
                            ),
                        ]
                    ],
                }
            )
        return make_json_response({})

    client, _ = mock_client_factory(handler)
    draft_file = tmp_path / "benchmarks_draft.yaml"
    rep = harvest_feedback(
        "exemplo_vendas",
        space_id="sp_prod_01",
        client=client,
        output_path=draft_file,
        include_audit=True,
        audit_days=30,
        existing_questions=["Pergunta ja coberta no benchmark oficial"],
    )

    assert rep.conversations_scanned == 1
    assert rep.audit_events_scanned == 1
    assert rep.duplicates_merged == 1
    assert rep.skipped_existing == 1
    assert len(rep.candidates) == 2
    assert rep.candidates[0].occurrences == 2
    assert len(rep.candidates[0].merged_variants) == 1
    assert draft_file.exists()
