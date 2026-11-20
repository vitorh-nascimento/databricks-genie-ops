"""Coleta de feedbacks negativos e conversas com falha (CLI + system.access.audit + deduplicação semântica)."""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from genieops.databricks_client import DatabricksClient

STOPWORDS_PT_EN = {
    "qual", "quais", "como", "para", "pelo", "pela", "dos", "das", "nos", "nas", "com",
    "sem", "por", "uma", "uns", "umas", "que", "foi", "foram", "este", "esta", "esse",
    "what", "which", "how", "the", "for", "from", "with", "that", "this", "are", "was",
}


@dataclass
class HarvestedCandidate:
    question: str
    reason: str
    conversation_id: str
    message_id: str
    generated_sql: str | None = None
    error: str | None = None
    source: str = "conversations_api"  # conversations_api | system.access.audit
    occurrences: int = 1
    merged_variants: list[str] = field(default_factory=list)


@dataclass
class HarvestReport:
    space_name: str
    conversations_scanned: int = 0
    audit_events_scanned: int = 0
    duplicates_merged: int = 0
    skipped_existing: int = 0
    candidates: list[HarvestedCandidate] = field(default_factory=list)
    draft_path: Path | None = None
    warnings: list[str] = field(default_factory=list)


def _normalize_question(text: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _content_tokens(text: str) -> set[str]:
    return {
        tok
        for tok in re.findall(r"[a-zà-ú0-9_]{2,}", _normalize_question(text))
        if tok not in STOPWORDS_PT_EN
    }


def semantic_similarity(q1: str, q2: str) -> float:
    """
    Calcula similaridade híbrida (Jaccard de tokens de conteúdo + SequenceMatcher)
    para deduplicar reformulações quase idênticas de usuários sem depender de embeddings externos.
    """
    n1, n2 = _normalize_question(q1), _normalize_question(q2)
    if not n1 or not n2:
        return 0.0
    if n1 == n2:
        return 1.0

    seq_ratio = difflib.SequenceMatcher(None, n1, n2).ratio()
    t1, t2 = _content_tokens(n1), _content_tokens(n2)
    if not t1 or not t2:
        return seq_ratio
    jaccard = len(t1 & t2) / len(t1 | t2)
    return round(0.55 * jaccard + 0.45 * seq_ratio, 4)


def _find_similar_candidate(
    question: str,
    candidates: list[HarvestedCandidate],
    threshold: float,
) -> HarvestedCandidate | None:
    best: HarvestedCandidate | None = None
    best_score = 0.0
    for cand in candidates:
        sim = semantic_similarity(question, cand.question)
        if sim >= threshold and sim > best_score:
            best = cand
            best_score = sim
    return best


def harvest_feedback(
    space_name: str,
    space_id: str,
    client: DatabricksClient,
    output_path: Path | None = None,
    max_conversations: int = 30,
    *,
    include_audit: bool = False,
    audit_days: int = 30,
    warehouse_id: str | None = None,
    existing_questions: list[str] | None = None,
    similarity_threshold: float = 0.78,
) -> HarvestReport:
    """
    Lê conversas recentes (e opcionalmente `system.access.audit` read-only),
    identifica mensagens com falha ou feedback negativo, aplica deduplicação semântica
    e exporta rascunho YAML pronto para revisão em `benchmarks.yaml`.
    """
    report = HarvestReport(space_name=space_name)
    existing_list = [q.strip() for q in (existing_questions or []) if q and q.strip()]

    def _is_already_in_benchmarks(question: str) -> bool:
        return any(
            semantic_similarity(question, eq) >= similarity_threshold for eq in existing_list
        )

    def _register_candidate(cand: HarvestedCandidate) -> None:
        if _is_already_in_benchmarks(cand.question):
            report.skipped_existing += 1
            return
        dup = _find_similar_candidate(cand.question, report.candidates, similarity_threshold)
        if dup is not None:
            dup.occurrences += 1
            if cand.question != dup.question and cand.question not in dup.merged_variants:
                dup.merged_variants.append(cand.question)
            report.duplicates_merged += 1
            return
        report.candidates.append(cand)

    # 1. Conversas recentes via Genie API
    conversations = client.list_conversations(space_id)[:max_conversations]
    for conv in conversations:
        conv_id = str(conv.get("conversation_id") or conv.get("id") or "")
        if not conv_id:
            continue
        report.conversations_scanned += 1
        messages = client.list_conversation_messages(space_id, conv_id)

        for msg in messages:
            status = str(msg.get("status", "")).upper()
            feedback = str(
                (msg.get("feedback") or {}).get("rating", "")
                if isinstance(msg.get("feedback"), dict)
                else msg.get("feedback") or ""
            ).upper()
            question = str(msg.get("content") or msg.get("question") or "").strip()
            if not question:
                continue

            is_negative = feedback in {"NEGATIVE", "THUMBS_DOWN", "BAD"}
            is_failed = status in {"FAILED", "CANCELLED"}
            if not (is_negative or is_failed):
                continue

            gen_sql: str | None = None
            for att in msg.get("attachments", []) or []:
                if isinstance(att, dict) and isinstance(att.get("query"), dict) and att["query"].get("query"):
                    gen_sql = str(att["query"]["query"])
                    break

            err_obj = msg.get("error") or {}
            err_msg = err_obj.get("error") if isinstance(err_obj, dict) else str(err_obj or "")

            _register_candidate(
                HarvestedCandidate(
                    question=question,
                    reason="NEGATIVE_FEEDBACK" if is_negative else f"STATUS_{status}",
                    conversation_id=conv_id,
                    message_id=str(msg.get("message_id") or msg.get("id") or ""),
                    generated_sql=gen_sql,
                    error=err_msg or None,
                    source="conversations_api",
                )
            )

    # 2. Opcional: eventos de feedback/comentário via system.access.audit (read-only)
    if include_audit:
        safe_days = max(1, min(int(audit_days), 90))
        safe_space = re.sub(r"[^A-Za-z0-9_-]", "", space_id)
        audit_sql = (
            "SELECT event_time, action_name, request_params "
            "FROM system.access.audit "
            "WHERE service_name = 'genie' "
            "AND action_name IN ('updateConversationMessageFeedback', 'createConversationMessageComment') "
            f"AND event_date >= current_date() - INTERVAL {safe_days} DAYS "
            "ORDER BY event_time DESC LIMIT 200"
        )
        try:
            qres = client.execute_readonly_sql(audit_sql, warehouse_id=warehouse_id)
            for row in qres.rows:
                if not row or len(row) < 3:
                    continue
                action_name = str(row[1] or "")
                raw_params = row[2]
                params: dict[str, Any] = {}
                if isinstance(raw_params, dict):
                    params = raw_params
                elif isinstance(raw_params, str) and raw_params.strip():
                    try:
                        parsed = json.loads(raw_params)
                        if isinstance(parsed, dict):
                            params = parsed
                    except json.JSONDecodeError:
                        params = {"raw": raw_params}

                row_space = str(params.get("space_id") or "")
                if safe_space and row_space and row_space != safe_space:
                    continue

                report.audit_events_scanned += 1
                rating = str(params.get("rating") or params.get("feedback_rating") or "").upper()
                if action_name == "updateConversationMessageFeedback" and rating not in {
                    "",
                    "NEGATIVE",
                    "THUMBS_DOWN",
                    "BAD",
                }:
                    continue

                question = str(
                    params.get("question")
                    or params.get("content")
                    or params.get("comment")
                    or ""
                ).strip()
                if not question:
                    continue

                _register_candidate(
                    HarvestedCandidate(
                        question=question,
                        reason=f"AUDIT_{action_name}",
                        conversation_id=str(params.get("conversation_id") or "audit"),
                        message_id=str(params.get("message_id") or "audit"),
                        error=str(params.get("comment") or "") or None,
                        source="system.access.audit",
                    )
                )
        except Exception as exc:
            report.warnings.append(f"system.access.audit indisponível ou sem permissão: {exc}")

    # Ordena candidatos por maior frequência de ocorrência primeiro
    report.candidates.sort(key=lambda c: (-c.occurrences, c.question.lower()))

    if output_path is not None:
        draft_questions: list[dict[str, Any]] = []
        for idx, cand in enumerate(report.candidates, start=1):
            criteria = [
                f"Origem: {cand.source} (conv={cand.conversation_id}, motivo={cand.reason}, ocorrencias={cand.occurrences})"
            ]
            if cand.merged_variants:
                criteria.append(f"Variantes agrupadas: {' | '.join(cand.merged_variants[:3])}")
            draft_questions.append(
                {
                    "id": f"harvest_{idx:02d}",
                    "question": cand.question,
                    "ground_truth_sql": "<PREENCHER_SQL_VALIDADO>",
                    "domain": "Feedback Produção",
                    "difficulty": "medium",
                    "tags": ["harvested", cand.reason.lower()],
                    "mode": "chat",
                    "semantic_criteria": criteria,
                }
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(
                {"questions": draft_questions},
                fh,
                sort_keys=False,
                allow_unicode=True,
                width=110,
            )
        report.draft_path = output_path

    return report
