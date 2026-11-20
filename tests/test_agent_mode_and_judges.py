"""Testes unitários para Agent Mode API (Streaming SSE) e LLM-as-a-Judge plugável."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from genieops.agent_mode import AgentModeClient, parse_sse_lines
from genieops.benchmark import run_benchmark
from genieops.history import HistoryStore
from genieops.judges import (
    DatabricksFoundationModelJudge,
    HeuristicRubricJudge,
    OpenAICompatibleJudge,
)
from genieops.models import BenchmarkCase


def _make_sse_body(frames: list[tuple[str, dict]]) -> bytes:
    chunks = []
    for ev, data in frames:
        chunks.append(f"event: {ev}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n")
    return "".join(chunks).encode("utf-8")


def test_parse_sse_lines_and_agent_mode_stream_full():
    sse_payload = _make_sse_body(
        [
            (
                "response.created",
                {"type": "response.created", "response": {"id": "resp_1", "conversation_id": "conv_1"}},
            ),
            (
                "reasoning",
                {"type": "reasoning", "text": "Consultar mv_receita_comercial e volume de políticas."},
            ),
            (
                "response.output_item.done",
                {
                    "type": "response.output_item.done",
                    "item": {
                        "type": "function_call",
                        "call_id": "c1",
                        "name": "execute_sql",
                        "arguments": json.dumps(
                            {"sql": "SELECT regiao, MEASURE(receita_liquida) FROM mv_receita_comercial GROUP BY regiao"}
                        ),
                    },
                },
            ),
            (
                "response.output_item.done",
                {
                    "type": "response.output_item.done",
                    "item": {
                        "type": "function_call",
                        "call_id": "c2",
                        "name": "search_context_files",
                        "arguments": json.dumps({"query": "política de desconto enterprise"}),
                    },
                },
            ),
            (
                "response.completed",
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_1",
                        "conversation_id": "conv_1",
                        "status": "completed",
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": (
                                            "A receita líquida no Sudeste liderou o trimestre, respeitando a política "
                                            "de desconto máximo de 15% [1](https://adb.example/explore/data/volumes/cat/sch/vol?filePreviewPath=politica.pdf)."
                                        ),
                                    }
                                ],
                            }
                        ],
                    },
                },
            ),
        ]
    )

    # Verifica parser isoladamente
    parsed = list(parse_sse_lines(sse_payload.decode("utf-8").splitlines()))
    assert len(parsed) == 5

    # Verifica AgentModeClient com MockTransport
    captured_requests: list[dict] = []

    def transport_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, content=sse_payload, headers={"content-type": "text/event-stream"})

    client = AgentModeClient(
        host="https://adb-mock.azuredatabricks.net",
        token="mock-ephemeral-token",
        transport=httpx.MockTransport(transport_handler),
    )

    seen_events: list[str] = []
    res = client.stream_response(
        space_id="0123456789abcdef0123456789abcdef",
        question="Qual foi a receita e a política de desconto?",
        execution_mode="FLASH",
        on_event=lambda ev: seen_events.append(ev.event_type),
    )

    assert res.status == "COMPLETED"
    assert res.conversation_id == "conv_1"
    assert res.response_id == "resp_1"
    assert len(res.executed_sqls) == 1
    assert "mv_receita_comercial" in res.executed_sqls[0]
    assert res.document_searches == ["política de desconto enterprise"]
    assert len(res.citations) == 1
    assert res.citations[0]["kind"] == "volume_document"
    assert "response.completed" in seen_events
    assert captured_requests[0]["execution_mode"] == "FLASH"


def test_agent_mode_detects_volume_indexing_pending(exemplo_bundle, tmp_path: Path):
    failed_sse = _make_sse_body(
        [
            (
                "response.failed",
                {
                    "type": "response.failed",
                    "response": {
                        "error": {
                            "code": "volume_content_search_failed",
                            "message": "Volume index is still building.",
                        }
                    },
                },
            )
        ]
    )
    agent_client = AgentModeClient(
        host="https://adb-mock.azuredatabricks.net",
        token="mock-token",
        transport=httpx.MockTransport(lambda _req: httpx.Response(200, content=failed_sse)),
    )
    history = HistoryStore(db_path=tmp_path / "h.db")
    rec, _ = run_benchmark(
        exemplo_bundle,
        env_name="dev",
        mode="agent",
        space_id="0123456789abcdef0123456789abcdef",
        agent_client=agent_client,
        history=history,
        ids=[exemplo_bundle.benchmarks.questions[0].id],
    )
    assert rec.excluded == 1
    assert rec.items[0].status == "EXCLUDED"


def test_pluggable_judges_heuristic_databricks_and_openai():
    case = BenchmarkCase(
        id="ag_01",
        question="Qual a política de desconto Enterprise e o impacto na receita?",
        mode="agent",
        expected_tables=["mv_receita_comercial"],
        evaluation_note="Deve citar o documento de política comercial e usar a Metric View.",
        semantic_criteria=["Citar limite de desconto", "Referenciar segmento Enterprise"],
    )

    # 1. HeuristicRubricJudge
    h_judge = HeuristicRubricJudge()
    verdict = h_judge.evaluate(
        case,
        answer_text="Conforme a política comercial [1](https://host/volumes/a/b/c?filePreviewPath=pol.pdf), o limite de desconto para o segmento Enterprise é de 15%.",
        executed_sqls=["SELECT segmento, MEASURE(receita_liquida) FROM mv_receita_comercial GROUP BY segmento"],
        citations=[{"index": "1", "url": "https://host/volumes/a/b/c?filePreviewPath=pol.pdf", "kind": "volume_document"}],
    )
    assert verdict.passed is True
    assert verdict.score >= 85.0

    # 2. DatabricksFoundationModelJudge
    dbx_transport = httpx.MockTransport(
        lambda _req: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "passed": True,
                                    "score": 94,
                                    "reasoning": "Resposta completa com citação documental e SQL correto.",
                                    "criteria_checks": [{"criterion": "Citação", "passed": True}],
                                }
                            )
                        }
                    }
                ]
            },
        )
    )
    dbx_judge = DatabricksFoundationModelJudge(
        endpoint="databricks-meta-llama-3-3-70b-instruct",
        host="https://adb-mock.azuredatabricks.net",
        token="mock-token",
        transport=dbx_transport,
    )
    v_dbx = dbx_judge.evaluate(case, "Resposta completa com citação.")
    assert v_dbx.passed is True
    assert v_dbx.score == 94.0
    assert v_dbx.provider == "databricks"

    # 3. OpenAICompatibleJudge
    oai_transport = httpx.MockTransport(
        lambda _req: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '```json\n{"passed": false, "score": 35, "reasoning": "Faltou citar a política."}\n```'
                        }
                    }
                ]
            },
        )
    )
    oai_judge = OpenAICompatibleJudge(
        base_url="https://api.mock.local/v1",
        api_key="test-key",
        model="gpt-4o-mini",
        transport=oai_transport,
    )
    v_oai = oai_judge.evaluate(case, "Resposta incompleta.")
    assert v_oai.passed is False
    assert v_oai.score == 35.0
    assert v_oai.provider == "openai"
