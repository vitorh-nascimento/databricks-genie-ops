"""Cliente Streaming SSE para a Databricks Genie Agent Mode API (Responses API)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from genieops.models import SpaceBundle

ExecutionMode = Literal["STANDARD", "FLASH"]

CITATION_RE = re.compile(r"\[(\d+)\]\((https?://[^)\s]+)\)")


@dataclass
class AgentStreamEvent:
    """Evento individual recebido via Server-Sent Events da Agent Mode API."""

    event_type: str
    data: dict[str, Any]
    timestamp_ms: float = 0.0


@dataclass
class AgentToolCall:
    """Chamada de ferramenta executada pelo Genie Agent (execute_sql ou search_context_files)."""

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    output: str | None = None
    call_id: str | None = None


@dataclass
class AgentResponseResult:
    """Resultado consolidado de um turno da Genie Agent Mode API."""

    status: str  # COMPLETED | FAILED | CANCELLED
    conversation_id: str | None = None
    response_id: str | None = None
    final_answer: str = ""
    reasoning_steps: list[str] = field(default_factory=list)
    tool_calls: list[AgentToolCall] = field(default_factory=list)
    executed_sqls: list[str] = field(default_factory=list)
    document_searches: list[str] = field(default_factory=list)
    citations: list[dict[str, str]] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    latency_ms: float = 0.0
    events: list[AgentStreamEvent] = field(default_factory=list)

    @property
    def is_volume_indexing_pending(self) -> bool:
        return self.error_code == "volume_content_search_failed"


def parse_sse_lines(lines: Iterable[str]) -> Iterator[tuple[str | None, dict[str, Any]]]:
    """Parser SSE robusto conforme RFC/HTML EventSource (`event:` + `data:` frames)."""
    current_event: str | None = None
    data_lines: list[str] = []

    def _flush() -> tuple[str | None, dict[str, Any]] | None:
        if not data_lines:
            return None
        raw = "\n".join(data_lines).strip()
        if not raw or raw == "[DONE]":
            return None
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                payload = {"raw": payload}
        except json.JSONDecodeError:
            payload = {"raw": raw}
        ev_type = current_event or str(payload.get("type") or "")
        return (ev_type or None), payload

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if line == "":
            flushed = _flush()
            current_event = None
            data_lines = []
            if flushed is not None:
                yield flushed
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            current_event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip())

    flushed = _flush()
    if flushed is not None:
        yield flushed


def extract_citations(markdown_text: str) -> list[dict[str, str]]:
    """Extrai citações `[n](url)` de respostas sintetizadas pelo Genie Agent."""
    citations: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in CITATION_RE.finditer(markdown_text or ""):
        idx, url = match.group(1), match.group(2)
        if url in seen:
            continue
        seen.add(url)
        kind = "volume_document" if "/volumes/" in url or "filePreviewPath=" in url else "genie_sql"
        citations.append({"index": idx, "url": url, "kind": kind})
    return citations


def resolve_databricks_auth(
    profile: str | None = None,
    host: str | None = None,
    token: str | None = None,
    executable: str = "databricks",
    runner: Any = None,
) -> tuple[str, str]:
    """
    Resolve `(host, bearer_token)` sem credenciais hardcoded:
    1. Usa `host`/`token` explícitos se fornecidos (ex.: injeção em testes ou env CI).
    2. Caso contrário, consulta `databricks auth env` / `databricks auth token --profile <profile>`.
    """
    resolved_host = (host or os.environ.get("DATABRICKS_HOST") or "").strip().rstrip("/")
    resolved_token = (token or os.environ.get("DATABRICKS_TOKEN") or "").strip()

    run_fn = runner or subprocess.run

    if not resolved_host:
        cmd = [executable, "auth", "env"]
        if profile:
            cmd.extend(["--profile", profile])
        res = run_fn(cmd, capture_output=True, text=True, check=False)
        if res.returncode == 0 and (res.stdout or "").strip():
            data = json.loads(res.stdout)
            env_map = data.get("env", data) if isinstance(data, dict) else {}
            resolved_host = str(env_map.get("DATABRICKS_HOST") or "").strip().rstrip("/")

    if not resolved_token:
        cmd = [executable, "auth", "token"]
        if profile:
            cmd.extend(["--profile", profile])
        res = run_fn(cmd, capture_output=True, text=True, check=False)
        if res.returncode == 0 and (res.stdout or "").strip():
            data = json.loads(res.stdout)
            if isinstance(data, dict):
                resolved_token = str(data.get("access_token") or data.get("token") or "").strip()

    if not resolved_host:
        raise ValueError(
            "Host do workspace Databricks não resolvido. Configure `--profile` autenticado ou `DATABRICKS_HOST`."
        )
    if not resolved_host.startswith("http"):
        resolved_host = f"https://{resolved_host}"
    if not resolved_token:
        raise ValueError(
            "Token de autenticação Databricks não resolvido. Execute `databricks auth login --profile <perfil>`."
        )
    return resolved_host, resolved_token


def _process_output_item(item: dict[str, Any], result: AgentResponseResult) -> None:
    """Extrai reasoning, tool calls (`execute_sql`/`search_context_files`) e mensagem final."""
    item_type = str(item.get("type") or "")

    if item_type == "reasoning":
        summary = item.get("summary") or item.get("content") or item.get("text")
        if isinstance(summary, list):
            for part in summary:
                txt = part.get("text", "") if isinstance(part, dict) else str(part)
                if txt and txt not in result.reasoning_steps:
                    result.reasoning_steps.append(txt)
        elif isinstance(summary, str) and summary and summary not in result.reasoning_steps:
            result.reasoning_steps.append(summary)

    elif item_type == "function_call":
        tool_name = str(item.get("name") or "unknown_tool")
        raw_args = item.get("arguments")
        if isinstance(raw_args, str):
            try:
                parsed_args = json.loads(raw_args) if raw_args.strip() else {}
            except json.JSONDecodeError:
                parsed_args = {"raw": raw_args}
        elif isinstance(raw_args, dict):
            parsed_args = raw_args
        else:
            parsed_args = {}

        call_id = str(item.get("call_id") or item.get("id") or "") or None
        existing = next((tc for tc in result.tool_calls if call_id and tc.call_id == call_id), None)
        if existing is None:
            result.tool_calls.append(
                AgentToolCall(tool_name=tool_name, arguments=parsed_args, call_id=call_id)
            )
        else:
            existing.arguments = parsed_args

        sql = parsed_args.get("sql")
        if sql and isinstance(sql, str) and sql not in result.executed_sqls:
            result.executed_sqls.append(sql)

        if tool_name == "search_context_files":
            query_txt = str(parsed_args.get("query") or parsed_args.get("search_query") or "")
            if query_txt and query_txt not in result.document_searches:
                result.document_searches.append(query_txt)

    elif item_type == "function_call_output":
        call_id = str(item.get("call_id") or "") or None
        output_text = str(item.get("output") or "")
        matched = next((tc for tc in result.tool_calls if call_id and tc.call_id == call_id), None)
        if matched is not None:
            matched.output = output_text
        elif result.tool_calls and result.tool_calls[-1].output is None:
            result.tool_calls[-1].output = output_text

    elif item_type == "message":
        parts = item.get("content") or []
        chunks: list[str] = []
        if isinstance(parts, str):
            chunks.append(parts)
        elif isinstance(parts, list):
            for part in parts:
                if isinstance(part, dict) and part.get("text"):
                    chunks.append(str(part["text"]))
                elif isinstance(part, str):
                    chunks.append(part)
        if chunks:
            result.final_answer = "\n".join(chunks)
            result.citations = extract_citations(result.final_answer)


class AgentModeClient:
    """
    Cliente streaming SSE para `/api/2.0/genie/agents/{space_id}/responses`.
    Suporta `STANDARD` e `FLASH`, follow-ups via `conversation_id`, callback de eventos em tempo real
    e injeção de `httpx.BaseTransport` para testes determinísticos offline.
    """

    def __init__(
        self,
        profile: str | None = None,
        host: str | None = None,
        token: str | None = None,
        timeout_s: float = 1800.0,
        transport: httpx.BaseTransport | None = None,
        cli_runner: Any = None,
    ) -> None:
        self.profile = profile
        self._host = host
        self._token = token
        self.timeout_s = timeout_s
        self._transport = transport
        self._cli_runner = cli_runner

    def _get_host_and_token(self) -> tuple[str, str]:
        return resolve_databricks_auth(
            profile=self.profile,
            host=self._host,
            token=self._token,
            runner=self._cli_runner,
        )

    def stream_response(
        self,
        space_id: str,
        question: str,
        conversation_id: str | None = None,
        execution_mode: ExecutionMode | None = None,
        enable_viz: bool = False,
        on_event: Callable[[AgentStreamEvent], None] | None = None,
    ) -> AgentResponseResult:
        """Executa uma pergunta na Genie Agent Mode API consumindo o stream SSE completo."""
        host, token = self._get_host_and_token()
        url = f"{host}/api/2.0/genie/agents/{space_id}/responses"

        body: dict[str, Any] = {
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": question}],
                }
            ]
        }
        if conversation_id:
            body["conversation_id"] = conversation_id
        elif execution_mode:
            # Conforme documentação oficial: execution_mode só é permitido em conversas novas
            body["execution_mode"] = execution_mode
        if enable_viz:
            body["enable_viz"] = True

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        t0 = time.perf_counter()
        result = AgentResponseResult(status="FAILED")

        client_kwargs: dict[str, Any] = {"timeout": httpx.Timeout(self.timeout_s)}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport

        with httpx.Client(**client_kwargs) as http_client:
            with http_client.stream("POST", url, headers=headers, json=body) as resp:
                if resp.status_code >= 400:
                    err_body = resp.read().decode("utf-8", errors="replace")
                    result.status = "FAILED"
                    result.error_code = f"HTTP_{resp.status_code}"
                    result.error_message = err_body[:500]
                    result.latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                    return result

                for ev_name, payload in parse_sse_lines(resp.iter_lines()):
                    ev_type = ev_name or str(payload.get("type") or "unknown")
                    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                    stream_ev = AgentStreamEvent(
                        event_type=ev_type,
                        data=payload,
                        timestamp_ms=elapsed_ms,
                    )
                    result.events.append(stream_ev)
                    if on_event is not None:
                        on_event(stream_ev)

                    self._apply_event(ev_type, payload, result)

        result.latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return result

    @staticmethod
    def _apply_event(ev_type: str, payload: dict[str, Any], result: AgentResponseResult) -> None:
        if ev_type == "response.created":
            resp_obj = payload.get("response") or payload
            if isinstance(resp_obj, dict):
                result.conversation_id = str(
                    resp_obj.get("conversation_id") or payload.get("conversation_id") or ""
                ) or result.conversation_id
                result.response_id = str(
                    resp_obj.get("id") or payload.get("response_id") or ""
                ) or result.response_id

        elif ev_type in ("response.output_item.done", "response.output_item.added", "response.output_item.updated"):
            item = payload.get("item")
            if isinstance(item, dict):
                if ev_type == "response.output_item.done" or item.get("type") == "reasoning":
                    _process_output_item(item, result)

        elif ev_type in ("reasoning", "function_call", "function_call_output", "message"):
            _process_output_item({"type": ev_type, **payload}, result)

        elif ev_type == "response.completed":
            resp_obj = payload.get("response") or {}
            status_val = str(resp_obj.get("status") or "completed").upper()
            result.status = "CANCELLED" if status_val == "CANCELLED" else "COMPLETED"
            if resp_obj.get("conversation_id"):
                result.conversation_id = str(resp_obj["conversation_id"])
            if resp_obj.get("id"):
                result.response_id = str(resp_obj["id"])
            for item in resp_obj.get("output", []) or []:
                if isinstance(item, dict):
                    _process_output_item(item, result)

        elif ev_type == "response.failed":
            result.status = "FAILED"
            resp_obj = payload.get("response") or payload
            err_obj = resp_obj.get("error") if isinstance(resp_obj, dict) else {}
            if isinstance(err_obj, dict):
                result.error_code = str(err_obj.get("code") or "") or None
                result.error_message = str(err_obj.get("message") or err_obj.get("error") or "") or None
            else:
                result.error_message = str(err_obj or "Agent response failed.")

    def cancel_response(
        self,
        space_id: str,
        conversation_id: str,
        response_id: str,
        executable: str = "databricks",
    ) -> dict[str, Any]:
        """Cancela uma execução em andamento na Agent Mode API via CLI oficial."""
        cmd = [
            executable,
            "genie",
            "genie-cancel-response",
            space_id,
            conversation_id,
            response_id,
            "-o",
            "json",
        ]
        if self.profile:
            cmd.extend(["--profile", self.profile])
        run_fn = self._cli_runner or subprocess.run
        res = run_fn(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            raise RuntimeError(f"Falha ao cancelar resposta Agent Mode: {res.stderr or res.stdout}")
        return json.loads(res.stdout) if (res.stdout or "").strip() else {"status": "cancelled"}


def simulate_agent_stream(question: str, bundle: SpaceBundle) -> Iterator[AgentStreamEvent]:
    """
    Gera um stream SSE determinístico de simulação local (para preview no Painel Web
    quando nenhum workspace Databricks ativo está conectado).
    """
    conv_id = "sim_conv_000001"
    resp_id = "sim_resp_000001"

    yield AgentStreamEvent(
        event_type="response.created",
        data={"type": "response.created", "response": {"id": resp_id, "conversation_id": conv_id}},
        timestamp_ms=15.0,
    )

    primary_src = (
        bundle.sources.metric_views[0].identifier
        if bundle.sources.metric_views
        else (bundle.sources.tables[0].identifier if bundle.sources.tables else "catalog.schema.tabela")
    )
    has_volume = bool(bundle.sources.volumes)

    yield AgentStreamEvent(
        event_type="reasoning",
        data={
            "type": "reasoning",
            "text": (
                f"Analisando pergunta sobre o domínio '{bundle.space.title}'. "
                f"Selecionando fonte governada `{primary_src}`"
                + (f" e volume documental `{bundle.sources.volumes[0].path}`." if has_volume else ".")
            ),
        },
        timestamp_ms=110.0,
    )

    matched_sql = next(
        (b.ground_truth_sql for b in bundle.benchmarks.questions if b.ground_truth_sql),
        f"SELECT * FROM {primary_src} LIMIT 10",
    )

    yield AgentStreamEvent(
        event_type="response.output_item.done",
        data={
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "call_id": "call_sql_1",
                "name": "execute_sql",
                "arguments": json.dumps({"sql": matched_sql}, ensure_ascii=False),
            },
        },
        timestamp_ms=260.0,
    )

    yield AgentStreamEvent(
        event_type="response.output_item.done",
        data={
            "type": "response.output_item.done",
            "item": {
                "type": "function_call_output",
                "call_id": "call_sql_1",
                "output": "| dimensao | valor_simulado |\n|---|---|\n| Enterprise | 1,420,500.00 |\n| SMB | 685,200.00 |",
            },
        },
        timestamp_ms=420.0,
    )

    if has_volume:
        yield AgentStreamEvent(
            event_type="response.output_item.done",
            data={
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "call_id": "call_doc_1",
                    "name": "search_context_files",
                    "arguments": json.dumps({"query": question}, ensure_ascii=False),
                },
            },
            timestamp_ms=540.0,
        )

    final_text = (
        f"**Síntese (Preview Local — `{bundle.space.name}`):**\n\n"
        f"Consulta avaliada com base na especificação declarativa (`{primary_src}`). "
        f"Em modo conectado ao workspace Databricks, o Agent Mode executa SQL real no SQL Warehouse "
        f"e pesquisa documentos nos UC Volumes configurados."
    )

    yield AgentStreamEvent(
        event_type="response.completed",
        data={
            "type": "response.completed",
            "response": {
                "id": resp_id,
                "conversation_id": conv_id,
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": final_text}],
                    }
                ],
            },
        },
        timestamp_ms=680.0,
    )
