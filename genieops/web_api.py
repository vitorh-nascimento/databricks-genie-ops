"""Backend FastAPI do Painel Web Local do Databricks GenieOps (REST + SSE)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from genieops import __version__
from genieops.agent_mode import AgentModeClient, ExecutionMode, simulate_agent_stream
from genieops.benchmark import run_benchmark
from genieops.compiler import compile_space, payload_hash
from genieops.diagnoser import FIX_LEVER_HIERARCHY, diagnose_run
from genieops.history import HistoryStore
from genieops.judges import JudgeProviderName, create_judge
from genieops.linter import lint_space
from genieops.loader import list_spaces, load_space, resolve_env_config
from genieops.models import BenchmarkCase
from genieops.uc_export import build_uc_export_plan


class AgentStreamRequest(BaseModel):
    question: str
    env: str = "dev"
    execution_mode: ExecutionMode = "STANDARD"
    live_mode: bool = False
    judge_provider: JudgeProviderName = "heuristic"
    evaluation_note: str | None = None


class OfflineBenchmarkRequest(BaseModel):
    env: str = "dev"
    ids: list[str] | None = None
    only_failed: bool = False


def create_app(
    base_dir: Path | None = None,
    history_db_path: Path | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    """Cria a instância FastAPI configurada para o workspace GenieOps."""
    root = base_dir or Path.cwd()
    db_path = history_db_path or (root / ".genieops" / "history.db")
    web_dist = static_dir or (root / "web" / "dist")

    app = FastAPI(
        title="Databricks GenieOps — Painel Web Local",
        version=__version__,
        description="Observabilidade, Genie Health Check, Benchmarks, Diagnóstico e Agent Mode SSE.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _history() -> HistoryStore:
        return HistoryStore(db_path=db_path)

    def _get_bundle(name: str):
        try:
            return load_space(name, base_dir=root)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/health")
    def api_health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "spaces_count": len(list_spaces(base_dir=root)),
            "frontend_built": (web_dist / "index.html").exists(),
        }

    @app.get("/api/spaces")
    def api_list_spaces() -> dict[str, Any]:
        hist = _history()
        items: list[dict[str, Any]] = []
        for name in list_spaces(base_dir=root):
            bundle = load_space(name, base_dir=root)
            lint_rep = lint_space(bundle)
            latest = hist.get_latest_run(name)
            runs = hist.list_runs(name, limit=20)
            items.append(
                {
                    "name": bundle.space.name,
                    "title": bundle.space.title,
                    "description": bundle.space.description,
                    "owner": bundle.space.owner,
                    "domains": bundle.space.domains,
                    "default_env": bundle.space.default_env,
                    "environments": sorted(bundle.space.environments.keys()),
                    "counts": {
                        "tables": len(bundle.sources.tables),
                        "metric_views": len(bundle.sources.metric_views),
                        "volumes": len(bundle.sources.volumes),
                        "join_specs": len(bundle.instructions.join_specs),
                        "examples": len(bundle.instructions.example_question_sqls),
                        "benchmarks": len(bundle.benchmarks.questions),
                    },
                    "health": {
                        "score": lint_rep.health_score,
                        "passed": lint_rep.passed,
                        "errors": lint_rep.error_count,
                        "warnings": lint_rep.warning_count,
                        "infos": lint_rep.info_count,
                    },
                    "latest_run": asdict(latest) if latest else None,
                    "total_runs": len(runs),
                }
            )
        avg_health = (
            round(sum(x["health"]["score"] for x in items) / len(items), 1) if items else 0.0
        )
        scored_runs = [x["latest_run"]["accuracy_pct"] for x in items if x["latest_run"]]
        avg_acc = round(sum(scored_runs) / len(scored_runs), 1) if scored_runs else None
        return {
            "summary": {
                "total_spaces": len(items),
                "avg_health_score": avg_health,
                "avg_accuracy_pct": avg_acc,
                "total_benchmarks": sum(x["counts"]["benchmarks"] for x in items),
            },
            "spaces": items,
        }

    @app.get("/api/spaces/{name}")
    def api_get_space(name: str) -> dict[str, Any]:
        bundle = _get_bundle(name)
        compiled = compile_space(bundle)
        env_names = sorted(set(bundle.space.environments.keys()) | {bundle.space.default_env})
        resolved_envs = {
            e: resolve_env_config(bundle, e, base_dir=root).model_dump(by_alias=True)
            for e in env_names
        }
        return {
            "space": bundle.space.model_dump(by_alias=True),
            "sources": bundle.sources.model_dump(),
            "instructions": bundle.instructions.model_dump(),
            "benchmarks": bundle.benchmarks.model_dump(),
            "resolved_environments": resolved_envs,
            "config_hash": payload_hash(compiled),
        }

    @app.get("/api/spaces/{name}/lint")
    def api_lint_space(name: str) -> dict[str, Any]:
        bundle = _get_bundle(name)
        rep = lint_space(bundle)
        return {
            "space_name": rep.space_name,
            "health_score": rep.health_score,
            "passed": rep.passed,
            "error_count": rep.error_count,
            "warning_count": rep.warning_count,
            "info_count": rep.info_count,
            "issues": [asdict(i) for i in rep.issues],
        }

    @app.get("/api/spaces/{name}/runs")
    def api_list_runs(name: str, limit: int = Query(default=25, ge=1, le=200)) -> dict[str, Any]:
        _get_bundle(name)
        hist = _history()
        runs = hist.list_runs(name, limit=limit)
        return {
            "space_name": name,
            "runs": [asdict(r) for r in runs],
        }

    @app.get("/api/spaces/{name}/runs/{run_id}")
    def api_get_run(name: str, run_id: str) -> dict[str, Any]:
        _get_bundle(name)
        hist = _history()
        run = hist.get_run(run_id)
        if run is None or run.space_name != name:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' não encontrado para '{name}'.")
        prev = hist.get_previous_run(name, run_id)
        diff = hist.compare_runs(prev, run) if prev is not None else None
        return {
            "run": asdict(run),
            "regression_diff": asdict(diff) if diff is not None else None,
        }

    @app.get("/api/spaces/{name}/diagnose")
    def api_diagnose(name: str, run_id: str | None = None) -> dict[str, Any]:
        bundle = _get_bundle(name)
        hist = _history()
        run = hist.get_run(run_id) if run_id else hist.get_latest_run(name)
        if run is None:
            return {
                "space_name": name,
                "run_id": None,
                "total_failures": 0,
                "diagnoses": [],
                "hierarchy": FIX_LEVER_HIERARCHY,
            }
        diag = diagnose_run(run, bundle)
        return {
            "space_name": diag.space_name,
            "run_id": diag.run_id,
            "total_failures": diag.total_failures,
            "diagnoses": [asdict(d) for d in diag.diagnoses],
            "hierarchy": FIX_LEVER_HIERARCHY,
        }

    @app.post("/api/spaces/{name}/benchmark/offline")
    def api_run_offline_benchmark(name: str, req: OfflineBenchmarkRequest) -> dict[str, Any]:
        bundle = _get_bundle(name)
        hist = _history()
        record, diff = run_benchmark(
            bundle,
            env_name=req.env,
            mode="offline",
            history=hist,
            ids=req.ids,
            only_failed=req.only_failed,
        )
        return {
            "run": asdict(record),
            "regression_diff": asdict(diff) if diff is not None else None,
        }

    @app.get("/api/spaces/{name}/export-delta/preview")
    def api_export_delta_preview(
        name: str,
        catalog: str = Query(default="analytics_ops"),
        schema: str = Query(default="genieops_audit"),
        schema_mode: Literal["four_tables", "events"] = Query(default="four_tables"),
        limit: int = Query(default=20, ge=1, le=200),
    ) -> dict[str, Any]:
        bundle = _get_bundle(name)
        hist = _history()
        try:
            plan = build_uc_export_plan(
                bundle,
                hist,
                catalog=catalog,
                schema=schema,
                schema_mode=schema_mode,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "space_name": plan.space_name,
            "catalog": plan.catalog,
            "schema": plan.schema,
            "schema_mode": plan.schema_mode,
            "runs_exported": plan.runs_exported,
            "ddl_count": len(plan.ddl_statements),
            "dml_count": len(plan.dml_statements),
            "sql": plan.full_sql(),
        }

    @app.post("/api/spaces/{name}/agent/stream")
    def api_agent_stream(name: str, req: AgentStreamRequest) -> StreamingResponse:
        bundle = _get_bundle(name)
        env_cfg = resolve_env_config(bundle, req.env, base_dir=root)
        eval_case = BenchmarkCase(
            id="playground_live",
            question=req.question,
            mode="agent",
            evaluation_note=req.evaluation_note
            or "Responder de forma fundamentada citando fontes/SQL utilizados.",
            expected_tables=[
                s.identifier for s in (bundle.sources.tables + bundle.sources.metric_views)
            ],
        )

        def _sse_frame(event_name: str, data: dict[str, Any]) -> str:
            return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        def _event_generator() -> Iterator[str]:
            executed_sqls: list[str] = []
            reasoning_steps: list[str] = []
            final_answer = ""

            if not req.live_mode:
                for ev in simulate_agent_stream(req.question, bundle):
                    if ev.event_type == "reasoning":
                        reasoning_steps.append(str(ev.data.get("text") or ""))
                    elif ev.event_type == "response.output_item.done":
                        item = ev.data.get("item") or {}
                        if item.get("type") == "function_call" and item.get("name") == "execute_sql":
                            try:
                                args = json.loads(item.get("arguments") or "{}")
                                if args.get("sql"):
                                    executed_sqls.append(str(args["sql"]))
                            except json.JSONDecodeError:
                                pass
                    elif ev.event_type == "response.completed":
                        out = (ev.data.get("response") or {}).get("output") or []
                        for item in out:
                            if item.get("type") == "message":
                                parts = item.get("content") or []
                                final_answer = "\n".join(str(p.get("text") or "") for p in parts)
                    yield _sse_frame(
                        ev.event_type,
                        {"event_type": ev.event_type, "timestamp_ms": ev.timestamp_ms, "payload": ev.data},
                    )
            else:
                if not env_cfg.space_id:
                    yield _sse_frame(
                        "response.failed",
                        {
                            "event_type": "response.failed",
                            "payload": {
                                "error": {
                                    "code": "MISSING_SPACE_ID",
                                    "message": f"space_id não configurado para o ambiente '{req.env}'.",
                                }
                            },
                        },
                    )
                    return

                collected: list[str] = []

                def _capture(ev) -> None:
                    collected.append(
                        _sse_frame(
                            ev.event_type,
                            {"event_type": ev.event_type, "timestamp_ms": ev.timestamp_ms, "payload": ev.data},
                        )
                    )

                try:
                    agent_client = AgentModeClient(profile=env_cfg.profile)
                    res = agent_client.stream_response(
                        space_id=env_cfg.space_id,
                        question=req.question,
                        execution_mode=req.execution_mode,
                        on_event=_capture,
                    )
                    yield from collected
                    executed_sqls = res.executed_sqls
                    reasoning_steps = res.reasoning_steps
                    final_answer = res.final_answer
                except Exception as exc:
                    yield _sse_frame(
                        "response.failed",
                        {
                            "event_type": "response.failed",
                            "payload": {"error": {"code": "CLIENT_ERROR", "message": str(exc)}},
                        },
                    )
                    return

            # Avalia via LLM-as-a-Judge plugável ao final do stream
            try:
                judge = create_judge(req.judge_provider, profile=env_cfg.profile)
                verdict = judge.evaluate(
                    eval_case,
                    final_answer,
                    executed_sqls=executed_sqls,
                    reasoning_steps=reasoning_steps,
                )
                yield _sse_frame("judge.verdict", asdict(verdict))
            except Exception as exc:
                yield _sse_frame(
                    "judge.verdict",
                    {
                        "passed": False,
                        "score": 0.0,
                        "reasoning": f"Erro ao executar juiz '{req.judge_provider}': {exc}",
                        "provider": req.judge_provider,
                        "model": "error",
                        "criteria_checks": [],
                    },
                )

        return StreamingResponse(_event_generator(), media_type="text/event-stream")

    # Serve frontend build (web/dist) automaticamente se existir
    if (web_dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(web_dist / "assets")), name="assets")

    @app.get("/", include_in_schema=False)
    def serve_index():
        index_html = web_dist / "index.html"
        if index_html.exists():
            return FileResponse(index_html)
        return {
            "message": "Databricks GenieOps API ativa. Execute `npm.cmd run build` em `web/` para habilitar a interface React.",
            "docs_url": "/docs",
            "api_spaces": "/api/spaces",
        }

    return app
