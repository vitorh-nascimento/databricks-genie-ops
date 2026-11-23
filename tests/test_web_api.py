"""Testes unitários da API FastAPI do Painel Web Local (REST + SSE)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from genieops.web_api import create_app
from tests.conftest import REPO_ROOT


def test_web_api_full_workflow(tmp_path: Path):
    app = create_app(base_dir=REPO_ROOT, history_db_path=tmp_path / "web_history.db")
    client = TestClient(app)

    # 1. Health & Portfolio
    r_health = client.get("/api/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "ok"
    assert r_health.json()["spaces_count"] >= 1

    r_spaces = client.get("/api/spaces")
    assert r_spaces.status_code == 200
    spaces_data = r_spaces.json()
    assert spaces_data["summary"]["total_spaces"] >= 1
    assert any(s["name"] == "exemplo_vendas" for s in spaces_data["spaces"])

    # 2. Space Detail & Lint
    r_det = client.get("/api/spaces/exemplo_vendas")
    assert r_det.status_code == 200
    assert r_det.json()["space"]["name"] == "exemplo_vendas"

    r_lint = client.get("/api/spaces/exemplo_vendas/lint")
    assert r_lint.status_code == 200
    assert r_lint.json()["health_score"] >= 90

    # 3. Trigger Offline Benchmark & Inspect Runs + Diagnose
    r_bmk = client.post("/api/spaces/exemplo_vendas/benchmark/offline", json={"env": "dev"})
    assert r_bmk.status_code == 200
    run_id = r_bmk.json()["run"]["run_id"]
    assert r_bmk.json()["run"]["accuracy_pct"] == 100.0

    r_runs = client.get("/api/spaces/exemplo_vendas/runs")
    assert r_runs.status_code == 200
    assert len(r_runs.json()["runs"]) == 1

    r_run_det = client.get(f"/api/spaces/exemplo_vendas/runs/{run_id}")
    assert r_run_det.status_code == 200
    assert len(r_run_det.json()["run"]["items"]) == 32

    # 3b. Offline Benchmark com label + expand_paraphrases e UC Comments preview
    r_bmk_para = client.post(
        "/api/spaces/exemplo_vendas/benchmark/offline",
        json={"env": "dev", "label": "Rodada 4 - Completa", "expand_paraphrases": True},
    )
    assert r_bmk_para.status_code == 200
    assert r_bmk_para.json()["run"]["label"] == "Rodada 4 - Completa"
    assert r_bmk_para.json()["run"]["total"] == 96

    r_comments = client.get("/api/spaces/exemplo_vendas/uc-comments/preview")
    assert r_comments.status_code == 200
    assert "COMMENT ON TABLE" in r_comments.json()["sql"]
    assert "ALTER COLUMN" in r_comments.json()["sql"]

    r_diag = client.get("/api/spaces/exemplo_vendas/diagnose")
    assert r_diag.status_code == 200
    assert r_diag.json()["total_failures"] == 0
    assert len(r_diag.json()["hierarchy"]) == 8

    # 4. Delta Export Preview
    r_delta = client.get(
        "/api/spaces/exemplo_vendas/export-delta/preview",
        params={"catalog": "analytics_ops", "schema": "genieops_audit", "schema_mode": "four_tables"},
    )
    assert r_delta.status_code == 200
    assert r_delta.json()["ddl_count"] == 4
    assert "genie_opt_runs" in r_delta.json()["sql"]

    # 5. Agent Mode SSE Stream (preview local + Heuristic Judge)
    r_sse = client.post(
        "/api/spaces/exemplo_vendas/agent/stream",
        json={
            "question": "Qual foi a receita líquida por segmento?",
            "env": "dev",
            "execution_mode": "STANDARD",
            "live_mode": False,
            "judge_provider": "heuristic",
        },
    )
    assert r_sse.status_code == 200
    assert "text/event-stream" in r_sse.headers["content-type"]
    body = r_sse.text
    assert "event: response.created" in body
    assert "event: reasoning" in body
    assert "event: response.completed" in body
    assert "event: judge.verdict" in body
