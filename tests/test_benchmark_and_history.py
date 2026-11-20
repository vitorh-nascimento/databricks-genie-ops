"""Testes do motor de Benchmark (offline, live, eval-run) e histórico/regressão em SQLite."""

from __future__ import annotations

from pathlib import Path

from genieops.benchmark import run_benchmark
from genieops.history import HistoryStore
from genieops.models import SpaceBundle
from tests.conftest import FakeCompletedProcess, make_json_response


def test_offline_benchmark_and_regression_diff(
    exemplo_bundle: SpaceBundle, tmp_path: Path
) -> None:
    history = HistoryStore(db_path=tmp_path / "history.db")

    # Rodada 1: 1 caso propositalmente quebrado (tabela inexistente em sources.yaml)
    broken = exemplo_bundle.model_copy(deep=True)
    broken.benchmarks.questions[0].expected_tables = ["tabela_fantasma"]
    run1, diff1 = run_benchmark(broken, env_name="dev", mode="offline", history=history)
    assert diff1 is None
    assert run1.total == 22
    assert run1.passed == 21
    assert run1.failed == 1

    # Rodada 2: corrigido -> deve registrar fixed=['bmk_01'] e delta positivo
    run2, diff2 = run_benchmark(exemplo_bundle, env_name="dev", mode="offline", history=history)
    assert run2.passed == 22
    assert run2.failed == 0
    assert run2.accuracy_pct == 100.0
    assert diff2 is not None
    assert diff2.fixed == ["bmk_01"]
    assert diff2.regressed == []
    assert diff2.delta_accuracy > 0


def test_live_benchmark_with_result_set_equivalence(
    exemplo_bundle: SpaceBundle, tmp_path: Path, mock_client_factory
) -> None:
    history = HistoryStore(db_path=tmp_path / "history.db")

    def handler(cmd: list[str]) -> FakeCompletedProcess:
        cmd_str = " ".join(cmd)
        if "start-conversation" in cmd_str:
            return make_json_response({"conversation_id": "conv_1", "message_id": "msg_1"})
        if "get-message" in cmd_str:
            # Genie escreve SQL sintaticamente diferente (usa CTE e alias distinto), mas equivalente!
            return make_json_response(
                {
                    "status": "COMPLETED",
                    "attachments": [
                        {
                            "query": {
                                "query": "WITH f AS (SELECT valor_liquido FROM analytics_dev.sales_gold.fct_pedidos WHERE competencia_faturamento = '2026-01' AND status_pedido = 'Faturado') SELECT SUM(valor_liquido) AS total_vendas FROM f"
                            }
                        }
                    ],
                }
            )
        if "tools query" in cmd_str:
            return make_json_response(
                {"columns": ["total"], "rows": [["245000.50"]]}
            )
        return make_json_response({})

    client, _ = mock_client_factory(handler)
    record, _ = run_benchmark(
        exemplo_bundle,
        env_name="dev",
        mode="live",
        client=client,
        space_id="space_live_01",
        warehouse_id="wh_01",
        history=history,
        ids=["bmk_01"],
    )
    assert record.total == 1
    assert record.passed == 1
    assert record.items[0].result_match is True
    assert record.items[0].status == "GOOD"


def test_native_eval_run_wrapper_staged_gate(
    exemplo_bundle: SpaceBundle, tmp_path: Path, mock_client_factory
) -> None:
    history = HistoryStore(db_path=tmp_path / "history.db")

    def handler(cmd: list[str]) -> FakeCompletedProcess:
        cmd_str = " ".join(cmd)
        if "genie-create-eval-run" in cmd_str:
            return make_json_response({"eval_run_id": "eval_999"})
        if "genie-get-eval-run" in cmd_str:
            return make_json_response({"eval_run_id": "eval_999", "eval_run_status": "DONE"})
        if "genie-list-eval-results" in cmd_str:
            return make_json_response({"results": [{"result_id": "res_1"}, {"result_id": "res_2"}]})
        if "genie-get-eval-result-details" in cmd_str:
            if "res_1" in cmd_str:
                return make_json_response(
                    {
                        "question": exemplo_bundle.benchmarks.questions[0].question,
                        "result": "GOOD",
                        "actual_response": [{"response": "SELECT SUM(valor_liquido) FROM fct_pedidos"}],
                        "expected_response": [{"response": exemplo_bundle.benchmarks.questions[0].ground_truth_sql}],
                    }
                )
            return make_json_response(
                {
                    "question": exemplo_bundle.benchmarks.questions[1].question,
                    "result": "BAD",
                    "actual_response": [{"response": "SELECT SUM(valor_bruto) FROM fct_pedidos"}],
                    "expected_response": [{"response": exemplo_bundle.benchmarks.questions[1].ground_truth_sql}],
                }
            )
        return make_json_response({})

    client, runner = mock_client_factory(handler)
    record, _ = run_benchmark(
        exemplo_bundle,
        env_name="dev",
        mode="eval-run",
        client=client,
        space_id="space_eval_01",
        history=history,
        ids=["bmk_01", "bmk_02"],
    )
    assert record.total == 2
    assert record.passed == 1
    assert record.failed == 1
    assert record.accuracy_pct == 50.0
    # Confirma que benchmark_question_ids foi enviado no staged gate
    create_call = next(c for c in runner.calls if "genie-create-eval-run" in c)
    assert "benchmark_question_ids" in " ".join(create_call)
