"""Motor de Benchmark (offline, live via Conversation API e eval-run nativo) com equivalência de Result Sets."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable
from typing import Any, Literal

from genieops.agent_mode import AgentModeClient, AgentStreamEvent, ExecutionMode
from genieops.comparator import compare_result_sets
from genieops.compiler import compile_space, payload_hash
from genieops.databricks_client import DatabricksClient, QueryResult
from genieops.history import (
    BenchmarkItemResult,
    BenchmarkRunRecord,
    HistoryStore,
    RegressionDiff,
    percentile,
    utc_now_iso,
)
from genieops.judges import CallableJudgeAdapter, HeuristicRubricJudge, JudgeProvider
from genieops.models import BenchmarkCase, SpaceBundle

BenchmarkMode = Literal["offline", "live", "eval-run", "agent"]
LLMJudgeFn = Callable[[BenchmarkCase, str, str | None], tuple[bool, str]]


def evaluate_sql_structure(sql: str, case: BenchmarkCase) -> tuple[bool, float, list[str]]:
    """Camada 1: Validação estrutural e semântica (tabelas esperadas, cláusulas e critérios)."""
    if not sql or not sql.strip():
        return False, 0.0, ["SQL vazio ou não gerado."]

    sql_upper = re.sub(r"\s+", " ", sql).upper()
    issues: list[str] = []

    if case.expected_tables:
        found_any = any(
            t.upper() in sql_upper or t.split(".")[-1].upper() in sql_upper
            for t in case.expected_tables
        )
        if not found_any:
            issues.append(f"Tabela/Metric View esperada ausente: {case.expected_tables}")

    for clause in case.required_clauses:
        clause_norm = re.sub(r"\s+", " ", clause).strip()
        # Verifica cláusula completa ou, quando houver '=', valida o identificador/coluna principal
        if clause_norm.upper() in sql_upper:
            continue
        if "=" in clause_norm:
            lhs = clause_norm.split("=", 1)[0].strip().upper()
            if lhs and lhs in sql_upper:
                continue
        issues.append(f"Cláusula/termo obrigatório ausente: {clause}")

    passed = len(issues) == 0
    score = 100.0 if passed else max(0.0, 100.0 - len(issues) * 35.0)
    return passed, score, issues


def _known_source_names(bundle: SpaceBundle) -> set[str]:
    names: set[str] = set()
    for src in bundle.sources.tables + bundle.sources.metric_views:
        names.add(src.identifier.lower())
        names.add(src.identifier.split(".")[-1].lower())
    for fn in bundle.instructions.sql_functions:
        names.add(fn.identifier.lower())
        names.add(fn.identifier.split(".")[-1].lower())
    return names


def _expand_cases_with_paraphrases(cases: list[BenchmarkCase]) -> list[BenchmarkCase]:
    """Expande cada BenchmarkCase com suas paráfrases como casos independentes compartilhando o gabarito."""
    expanded: list[BenchmarkCase] = []
    for idx, case in enumerate(cases):
        base_id = case.id or f"case_{idx + 1:02d}"
        expanded.append(case)
        for p_idx, para in enumerate(case.paraphrases, start=1):
            para_clean = para.strip()
            if not para_clean:
                continue
            expanded.append(
                case.model_copy(
                    update={
                        "id": f"{base_id}__p{p_idx}",
                        "question": para_clean,
                        "paraphrases": [],
                        "tags": list(dict.fromkeys([*case.tags, "paraphrase", f"base:{base_id}"])),
                    }
                )
            )
    return expanded


def _select_cases(
    bundle: SpaceBundle,
    ids: list[str] | None = None,
    only_failed: bool = False,
    history: HistoryStore | None = None,
    expand_paraphrases: bool = False,
) -> list[BenchmarkCase]:
    cases = list(bundle.benchmarks.questions)
    if expand_paraphrases:
        cases = _expand_cases_with_paraphrases(cases)
    if ids:
        wanted = {i.strip() for i in ids if i.strip()}
        cases = [
            c
            for idx, c in enumerate(cases)
            if (c.id or f"case_{idx + 1}") in wanted
            or (c.id and c.id.split("__p")[0] in wanted)
        ]
    if only_failed and history is not None:
        latest = history.get_latest_run(bundle.space.name)
        if latest:
            failed_ids = {it.case_id for it in latest.items if it.status == "BAD"}
            cases = [c for idx, c in enumerate(cases) if (c.id or f"case_{idx + 1}") in failed_ids]
    return cases


def _extract_sql_and_text(message: dict[str, Any]) -> tuple[str | None, str | None]:
    sql: str | None = None
    texts: list[str] = []
    for att in message.get("attachments", []) or []:
        if isinstance(att, dict):
            query_obj = att.get("query") or {}
            if isinstance(query_obj, dict) and query_obj.get("query"):
                sql = str(query_obj["query"])
            text_obj = att.get("text") or {}
            if isinstance(text_obj, dict) and text_obj.get("content"):
                texts.append(str(text_obj["content"]))
    return sql, ("\n".join(texts) if texts else None)


def _finalize_run(
    bundle: SpaceBundle,
    env_name: str,
    mode: BenchmarkMode,
    items: list[BenchmarkItemResult],
    history: HistoryStore | None,
    label: str = "",
) -> tuple[BenchmarkRunRecord, RegressionDiff | None]:
    compiled = compile_space(bundle)
    cfg_hash = payload_hash(compiled)

    passed = sum(1 for i in items if i.status == "GOOD")
    failed = sum(1 for i in items if i.status == "BAD")
    needs_review = sum(1 for i in items if i.status == "NEEDS_REVIEW")
    excluded = sum(1 for i in items if i.status == "EXCLUDED")
    valid_denom = passed + failed
    accuracy = round((passed / valid_denom) * 100.0, 2) if valid_denom > 0 else 0.0

    latencies = [i.latency_ms for i in items if i.latency_ms > 0]
    avg_lat = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
    p50_lat = percentile(latencies, 50)
    p95_lat = percentile(latencies, 95)

    record = BenchmarkRunRecord(
        run_id=f"run_{uuid.uuid4().hex[:10]}",
        space_name=bundle.space.name,
        env=env_name,
        mode=mode,
        created_at=utc_now_iso(),
        total=len(items),
        passed=passed,
        failed=failed,
        needs_review=needs_review,
        excluded=excluded,
        accuracy_pct=accuracy,
        avg_latency_ms=avg_lat,
        p50_latency_ms=p50_lat,
        p95_latency_ms=p95_lat,
        config_hash=cfg_hash,
        label=label.strip(),
        items=items,
    )

    diff: RegressionDiff | None = None
    if history is not None:
        prev = history.get_latest_run(bundle.space.name)
        history.save_run(record)
        if prev is not None:
            diff = history.compare_runs(prev, record)

    return record, diff


def run_benchmark(
    bundle: SpaceBundle,
    env_name: str = "dev",
    mode: BenchmarkMode = "offline",
    client: DatabricksClient | None = None,
    space_id: str | None = None,
    warehouse_id: str | None = None,
    history: HistoryStore | None = None,
    ids: list[str] | None = None,
    only_failed: bool = False,
    rel_tol: float = 1e-4,
    abs_tol: float = 1e-2,
    llm_judge: LLMJudgeFn | None = None,
    judge_provider: JudgeProvider | None = None,
    agent_client: AgentModeClient | None = None,
    execution_mode: ExecutionMode = "STANDARD",
    on_agent_event: Callable[[AgentStreamEvent], None] | None = None,
    label: str = "",
    expand_paraphrases: bool = False,
) -> tuple[BenchmarkRunRecord, RegressionDiff | None]:
    """Executa a suíte de benchmark no modo especificado (`offline`, `live`, `eval-run`, `agent`)."""
    cases = _select_cases(
        bundle,
        ids=ids,
        only_failed=only_failed,
        history=history,
        expand_paraphrases=expand_paraphrases,
    )
    known_sources = _known_source_names(bundle)

    if mode == "offline":
        items = _run_offline(cases, known_sources)
        return _finalize_run(bundle, env_name, mode, items, history, label=label)

    resolved_judge: JudgeProvider | None = judge_provider
    if resolved_judge is None and llm_judge is not None:
        resolved_judge = CallableJudgeAdapter(llm_judge)

    if mode == "agent":
        if not space_id:
            raise ValueError(
                f"O modo 'agent' exige space_id válido configurado para o ambiente '{env_name}'."
            )
        resolved_agent_client = agent_client or AgentModeClient(
            profile=client.profile if client else None
        )
        items = _run_agent_mode(
            cases=cases,
            agent_client=resolved_agent_client,
            space_id=space_id,
            execution_mode=execution_mode,
            judge=resolved_judge or HeuristicRubricJudge(),
            on_event=on_agent_event,
        )
        return _finalize_run(bundle, env_name, mode, items, history, label=label)

    if client is None or not space_id:
        raise ValueError(
            f"O modo '{mode}' exige cliente Databricks configurado e space_id válido para o ambiente '{env_name}'."
        )

    if mode == "live":
        items = _run_live(
            cases=cases,
            client=client,
            space_id=space_id,
            warehouse_id=warehouse_id,
            rel_tol=rel_tol,
            abs_tol=abs_tol,
            llm_judge=llm_judge,
            judge_provider=resolved_judge,
        )
        return _finalize_run(bundle, env_name, mode, items, history, label=label)

    if mode == "eval-run":
        items = _run_native_eval(
            bundle=bundle,
            cases=cases,
            client=client,
            space_id=space_id,
            expand_paraphrases=expand_paraphrases,
        )
        return _finalize_run(bundle, env_name, mode, items, history, label=label)

    raise ValueError(f"Modo de benchmark desconhecido: {mode}")


def _run_offline(cases: list[BenchmarkCase], known_sources: set[str]) -> list[BenchmarkItemResult]:
    """Valida consistência estrutural e referencial da suíte localmente (zero custo, ideal para CI)."""
    results: list[BenchmarkItemResult] = []
    for idx, case in enumerate(cases):
        t0 = time.perf_counter()
        cid = case.id or f"case_{idx + 1:02d}"
        details: list[str] = []

        if case.mode == "agent" and not case.ground_truth_sql:
            if case.evaluation_note and case.evaluation_note.strip():
                status = "GOOD"
                score = 100.0
                details.append("Caso Agent Mode validado com evaluation_note preenchido.")
            else:
                status = "BAD"
                score = 0.0
                details.append("Caso Agent Mode sem evaluation_note.")
        else:
            ok, score, errs = evaluate_sql_structure(case.ground_truth_sql or "", case)
            details.extend(errs)
            # Valida se tabelas esperadas existem no sources.yaml
            if case.expected_tables and known_sources:
                missing = [
                    t
                    for t in case.expected_tables
                    if t.lower() not in known_sources and t.split(".")[-1].lower() not in known_sources
                ]
                if missing:
                    ok = False
                    score = max(0.0, score - 40.0)
                    details.append(f"Fonte(s) não declaradas em sources.yaml: {missing}")
            status = "GOOD" if ok else "BAD"

        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        results.append(
            BenchmarkItemResult(
                case_id=cid,
                question=case.question,
                domain=case.domain,
                difficulty=case.difficulty,
                mode=case.mode,
                status=status,
                semantic_score=score,
                result_match=None,
                expected_sql=case.ground_truth_sql,
                generated_sql=case.ground_truth_sql,
                latency_ms=elapsed_ms,
                error_message="; ".join(details) if status == "BAD" else None,
                details=details,
            )
        )
    return results


def _run_live(
    cases: list[BenchmarkCase],
    client: DatabricksClient,
    space_id: str,
    warehouse_id: str | None,
    rel_tol: float,
    abs_tol: float,
    llm_judge: LLMJudgeFn | None,
    judge_provider: JudgeProvider | None = None,
) -> list[BenchmarkItemResult]:
    """Avaliação real via Conversation API em 3 camadas: estrutural, equivalência de Result Set e LLM judge."""
    results: list[BenchmarkItemResult] = []
    effective_judge = judge_provider or (CallableJudgeAdapter(llm_judge) if llm_judge else None)

    for idx, case in enumerate(cases):
        cid = case.id or f"case_{idx + 1:02d}"
        details: list[str] = []
        msg, latency_ms = client.ask_and_wait(space_id, case.question)
        msg_status = str(msg.get("status", "")).upper()

        if msg_status != "COMPLETED":
            err_obj = msg.get("error") or {}
            err_msg = err_obj.get("error") if isinstance(err_obj, dict) else str(err_obj)
            results.append(
                BenchmarkItemResult(
                    case_id=cid,
                    question=case.question,
                    domain=case.domain,
                    difficulty=case.difficulty,
                    mode=case.mode,
                    status="BAD",
                    semantic_score=0.0,
                    result_match=False,
                    expected_sql=case.ground_truth_sql,
                    generated_sql=None,
                    latency_ms=round(latency_ms, 2),
                    error_message=err_msg or f"Status terminal inesperado: {msg_status}",
                    details=[f"Conversation status={msg_status}"],
                )
            )
            continue

        gen_sql, text_reply = _extract_sql_and_text(msg)

        # Casos Agent Mode / sem SQL canônico
        if case.mode == "agent" and not case.ground_truth_sql:
            if effective_judge is not None:
                verdict = effective_judge.evaluate(
                    case,
                    text_reply or "",
                    executed_sqls=[gen_sql] if gen_sql else [],
                )
                results.append(
                    BenchmarkItemResult(
                        case_id=cid,
                        question=case.question,
                        domain=case.domain,
                        difficulty=case.difficulty,
                        mode=case.mode,
                        status="GOOD" if verdict.passed else "BAD",
                        semantic_score=verdict.score,
                        result_match=None,
                        expected_sql=None,
                        generated_sql=gen_sql,
                        latency_ms=round(latency_ms, 2),
                        error_message=None if verdict.passed else verdict.reasoning,
                        details=[f"LLM-as-a-Judge ({verdict.provider}/{verdict.model}): {verdict.reasoning}"],
                    )
                )
            else:
                results.append(
                    BenchmarkItemResult(
                        case_id=cid,
                        question=case.question,
                        domain=case.domain,
                        difficulty=case.difficulty,
                        mode=case.mode,
                        status="NEEDS_REVIEW",
                        semantic_score=50.0,
                        result_match=None,
                        expected_sql=None,
                        generated_sql=gen_sql,
                        latency_ms=round(latency_ms, 2),
                        error_message=None,
                        details=["Caso Agent Mode aguardando revisão humana ou LLM-as-a-Judge."],
                    )
                )
            continue

        # Camada 1: Validação estrutural/semântica
        struct_ok, sem_score, struct_errs = evaluate_sql_structure(gen_sql or "", case)
        details.extend(struct_errs)

        # Camada 2: Equivalência de Result Set (evita falso negativo por SQL alternativo equivalente!)
        result_match: bool | None = None
        if gen_sql and case.ground_truth_sql:
            try:
                exp_res: QueryResult = client.execute_readonly_sql(
                    case.ground_truth_sql, warehouse_id=warehouse_id
                )
                act_res: QueryResult = client.execute_readonly_sql(
                    gen_sql, warehouse_id=warehouse_id
                )
                enforce_order = "ORDER BY" in case.ground_truth_sql.upper() and "LIMIT" in case.ground_truth_sql.upper()
                comp = compare_result_sets(
                    exp_res,
                    act_res,
                    rel_tol=rel_tol,
                    abs_tol=abs_tol,
                    enforce_order=enforce_order,
                )
                result_match = comp.equivalent
                details.append(f"ResultSet: {comp.reason}")
                if comp.differences:
                    details.extend(comp.differences[:3])
            except Exception as exc:
                result_match = False
                details.append(f"Erro ao executar comparação de Result Set: {exc}")

        # Decisão consolidada: equivalência matemática do Result Set prevalece quando disponível
        if result_match is True:
            final_status = "GOOD"
            sem_score = max(sem_score, 100.0)
        elif result_match is False:
            final_status = "BAD"
        else:
            final_status = "GOOD" if struct_ok else "BAD"

        results.append(
            BenchmarkItemResult(
                case_id=cid,
                question=case.question,
                domain=case.domain,
                difficulty=case.difficulty,
                mode=case.mode,
                status=final_status,
                semantic_score=sem_score,
                result_match=result_match,
                expected_sql=case.ground_truth_sql,
                generated_sql=gen_sql,
                latency_ms=round(latency_ms, 2),
                error_message="; ".join(details) if final_status == "BAD" else None,
                details=details,
            )
        )

    return results


def _run_native_eval(
    bundle: SpaceBundle,
    cases: list[BenchmarkCase],
    client: DatabricksClient,
    space_id: str,
    expand_paraphrases: bool = False,
) -> list[BenchmarkItemResult]:
    """Wrapper para a API nativa `genie-create-eval-run` com suporte a staged gates."""
    compiled = compile_space(bundle, expand_paraphrases=expand_paraphrases)
    question_to_hex = {
        q["question"][0]: q["id"] for q in compiled.get("benchmarks", {}).get("questions", [])
    }

    selected_hex_ids: list[str] | None = None
    total_compiled = len(compiled.get("benchmarks", {}).get("questions", []))
    if len(cases) < total_compiled:
        selected_hex_ids = [
            question_to_hex[c.question.strip()]
            for c in cases
            if c.question.strip() in question_to_hex
        ]

    t0 = time.perf_counter()
    created = client.create_eval_run(space_id, benchmark_question_ids=selected_hex_ids)
    eval_run_id = created.get("eval_run_id") or created.get("id")
    if not eval_run_id:
        raise RuntimeError(f"eval_run_id não retornado por genie-create-eval-run: {created}")

    # Polling até DONE
    while True:
        run_state = client.get_eval_run(space_id, eval_run_id)
        st = str(run_state.get("eval_run_status", "")).upper()
        if st in {"DONE", "COMPLETED", "FAILED", "CANCELLED"}:
            break
        if (time.perf_counter() - t0) > 600:
            raise TimeoutError(f"Timeout aguardando eval run {eval_run_id}")
        time.sleep(3.0)

    total_ms = (time.perf_counter() - t0) * 1000.0
    listed = client.list_eval_results(space_id, eval_run_id)
    eval_results = listed.get("results", listed.get("eval_results", [])) or []
    per_item_ms = round(total_ms / max(1, len(eval_results)), 2)

    case_by_question = {c.question.strip(): c for c in cases}
    items: list[BenchmarkItemResult] = []
    for idx, er in enumerate(eval_results):
        result_id = er.get("result_id") or er.get("id")
        detail = client.get_eval_result_details(space_id, eval_run_id, result_id) if result_id else er
        q_text = str(detail.get("question") or er.get("question") or f"Pergunta #{idx + 1}")
        matched_case = case_by_question.get(q_text.strip())

        raw_verdict = str(detail.get("result") or er.get("result") or "NEEDS_REVIEW").upper()
        if raw_verdict in {"GOOD", "PASS", "PASSED"}:
            status = "GOOD"
        elif raw_verdict in {"BAD", "FAIL", "FAILED"}:
            status = "BAD"
        else:
            status = "NEEDS_REVIEW"

        actual_resp = detail.get("actual_response") or []
        expected_resp = detail.get("expected_response") or []
        gen_sql = actual_resp[0].get("response") if actual_resp and isinstance(actual_resp[0], dict) else None
        exp_sql = expected_resp[0].get("response") if expected_resp and isinstance(expected_resp[0], dict) else (
            matched_case.ground_truth_sql if matched_case else None
        )

        items.append(
            BenchmarkItemResult(
                case_id=(matched_case.id if matched_case and matched_case.id else f"eval_{idx + 1:02d}"),
                question=q_text,
                domain=matched_case.domain if matched_case else "Geral",
                difficulty=matched_case.difficulty if matched_case else "medium",
                mode=matched_case.mode if matched_case else "chat",
                status=status,
                semantic_score=100.0 if status == "GOOD" else (50.0 if status == "NEEDS_REVIEW" else 0.0),
                result_match=True if status == "GOOD" else (False if status == "BAD" else None),
                expected_sql=exp_sql,
                generated_sql=gen_sql,
                latency_ms=per_item_ms,
                error_message=None if status == "GOOD" else f"Native eval verdict: {raw_verdict}",
                details=[f"Databricks eval_run_id={eval_run_id}", f"verdict={raw_verdict}"],
            )
        )

    return items


def _run_agent_mode(
    cases: list[BenchmarkCase],
    agent_client: AgentModeClient,
    space_id: str,
    execution_mode: ExecutionMode,
    judge: JudgeProvider,
    on_event: Callable[[AgentStreamEvent], None] | None = None,
) -> list[BenchmarkItemResult]:
    """Avaliação via Streaming SSE da Agent Mode API + LLM-as-a-Judge plugável."""
    results: list[BenchmarkItemResult] = []
    for idx, case in enumerate(cases):
        cid = case.id or f"case_{idx + 1:02d}"
        resp = agent_client.stream_response(
            space_id=space_id,
            question=case.question,
            execution_mode=execution_mode,
            on_event=on_event,
        )

        first_sql = resp.executed_sqls[0] if resp.executed_sqls else None

        if resp.status != "COMPLETED":
            err_detail = (
                "Volume ainda em indexação (volume_content_search_failed) — tente novamente em breve."
                if resp.is_volume_indexing_pending
                else (resp.error_message or f"Agent Mode retornou status={resp.status}")
            )
            results.append(
                BenchmarkItemResult(
                    case_id=cid,
                    question=case.question,
                    domain=case.domain,
                    difficulty=case.difficulty,
                    mode="agent",
                    status="EXCLUDED" if resp.is_volume_indexing_pending else "BAD",
                    semantic_score=0.0,
                    result_match=False,
                    expected_sql=case.ground_truth_sql,
                    generated_sql=first_sql,
                    latency_ms=resp.latency_ms,
                    error_message=err_detail,
                    details=[
                        f"AgentMode status={resp.status}",
                        f"error_code={resp.error_code or 'NONE'}",
                    ],
                )
            )
            continue

        verdict = judge.evaluate(
            case=case,
            answer_text=resp.final_answer,
            executed_sqls=resp.executed_sqls,
            reasoning_steps=resp.reasoning_steps,
            citations=resp.citations,
        )
        details = [
            f"AgentMode ({execution_mode}): {len(resp.executed_sqls)} SQL(s), "
            f"{len(resp.document_searches)} busca(s) documental(is), {len(resp.citations)} citação(ões)",
            f"Judge ({verdict.provider}/{verdict.model}): {verdict.reasoning}",
        ]
        results.append(
            BenchmarkItemResult(
                case_id=cid,
                question=case.question,
                domain=case.domain,
                difficulty=case.difficulty,
                mode="agent",
                status="GOOD" if verdict.passed else "BAD",
                semantic_score=verdict.score,
                result_match=None,
                expected_sql=case.ground_truth_sql,
                generated_sql=first_sql,
                latency_ms=resp.latency_ms,
                error_message=None if verdict.passed else verdict.reasoning,
                details=details,
            )
        )
    return results
