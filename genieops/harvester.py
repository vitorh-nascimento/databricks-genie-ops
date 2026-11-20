"""Coleta de feedbacks negativos e conversas com falha para enriquecer benchmarks.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from genieops.databricks_client import DatabricksClient


@dataclass
class HarvestedCandidate:
    question: str
    reason: str
    conversation_id: str
    message_id: str
    generated_sql: str | None = None
    error: str | None = None


@dataclass
class HarvestReport:
    space_name: str
    conversations_scanned: int = 0
    candidates: list[HarvestedCandidate] = field(default_factory=list)
    draft_path: Path | None = None


def harvest_feedback(
    space_name: str,
    space_id: str,
    client: DatabricksClient,
    output_path: Path | None = None,
    max_conversations: int = 30,
) -> HarvestReport:
    """
    Lê conversas recentes do Genie Space, identifica mensagens com falha ou feedback negativo
    e exporta um rascunho YAML pronto para revisão e incorporação em benchmarks.yaml.
    """
    report = HarvestReport(space_name=space_name)
    conversations = client.list_conversations(space_id)[:max_conversations]
    seen_questions: set[str] = set()

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

            q_key = question.lower()
            if q_key in seen_questions:
                continue
            seen_questions.add(q_key)

            gen_sql: str | None = None
            for att in msg.get("attachments", []) or []:
                if isinstance(att, dict) and isinstance(att.get("query"), dict) and att["query"].get("query"):
                    gen_sql = str(att["query"]["query"])
                    break

            err_obj = msg.get("error") or {}
            err_msg = err_obj.get("error") if isinstance(err_obj, dict) else str(err_obj or "")

            report.candidates.append(
                HarvestedCandidate(
                    question=question,
                    reason="NEGATIVE_FEEDBACK" if is_negative else f"STATUS_{status}",
                    conversation_id=conv_id,
                    message_id=str(msg.get("message_id") or msg.get("id") or ""),
                    generated_sql=gen_sql,
                    error=err_msg or None,
                )
            )

    if output_path is not None:
        draft_questions: list[dict[str, Any]] = []
        for idx, cand in enumerate(report.candidates, start=1):
            draft_questions.append(
                {
                    "id": f"harvest_{idx:02d}",
                    "question": cand.question,
                    "ground_truth_sql": "<PREENCHER_SQL_VALIDADO>",
                    "domain": "Feedback Produção",
                    "difficulty": "medium",
                    "tags": ["harvested", cand.reason.lower()],
                    "mode": "chat",
                    "semantic_criteria": [f"Origem: conv={cand.conversation_id}, motivo={cand.reason}"],
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
