"""Cliente wrapper para Databricks CLI com suporte completo a Genie Agents, SQL read-only e mocks."""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Any

READ_ONLY_SQL_RE = re.compile(
    r"^\s*(SELECT|WITH|SHOW|DESCRIBE|DESC|EXPLAIN)\b",
    re.IGNORECASE,
)
MUTATING_SQL_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY\s+INTO)\b",
    re.IGNORECASE,
)


class DatabricksCLIError(RuntimeError):
    """Erro retornado pela Databricks CLI."""

    def __init__(self, command: list[str], returncode: int, stderr: str, stdout: str = ""):
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout
        super().__init__(
            f"Databricks CLI falhou (rc={returncode}): {' '.join(command[:4])} — {stderr.strip() or stdout.strip()}"
        )


def assert_read_only_sql(sql: str) -> None:
    """Garante estritamente que apenas consultas SQL read-only sejam executadas pelo GenieOps."""
    cleaned = sql.strip().rstrip(";")
    if not cleaned:
        raise ValueError("Consulta SQL vazia não pode ser executada.")
    if not READ_ONLY_SQL_RE.match(cleaned):
        raise ValueError(f"Apenas SQL read-only é permitido (SELECT/WITH/SHOW/DESCRIBE/EXPLAIN): {cleaned[:80]}")
    # Remove literais entre aspas simples antes de checar palavras de mutação
    without_strings = re.sub(r"'[^']*'", "''", cleaned)
    if MUTATING_SQL_RE.search(without_strings):
        raise ValueError(f"Comando SQL bloqueado por conter operação de escrita/DDL: {cleaned[:80]}")


@dataclass
class QueryResult:
    """Resultado tabular padronizado retornado por consultas SQL no Databricks."""

    columns: list[str]
    rows: list[list[Any]]
    raw: Any = None


class DatabricksClient:
    """Encapsula chamadas à Databricks CLI (`databricks >= v1.0.0`)."""

    def __init__(
        self,
        profile: str | None = None,
        warehouse_id: str | None = None,
        executable: str = "databricks",
        runner: Any = None,
    ) -> None:
        self.profile = profile
        self.warehouse_id = warehouse_id
        self.executable = executable
        self._runner = runner or subprocess.run

    def _base_cmd(self, *args: str, json_output: bool = True) -> list[str]:
        cmd = [self.executable, *args]
        if self.profile:
            cmd.extend(["--profile", self.profile])
        if json_output:
            cmd.extend(["-o", "json"])
        return cmd

    def run_cli(self, *args: str, json_output: bool = True) -> Any:
        cmd = self._base_cmd(*args, json_output=json_output)
        res = self._runner(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            raise DatabricksCLIError(cmd, res.returncode, res.stderr or "", res.stdout or "")
        if not json_output:
            return res.stdout
        raw_out = (res.stdout or "").strip()
        if not raw_out:
            return {}
        try:
            return json.loads(raw_out)
        except json.JSONDecodeError:
            # Comandos DDL/DML sem result set em `aitools tools query` retornam texto plano mesmo com `-o json`
            return {"message": raw_out}

    # --- Workspace & Warehouses ---

    def ensure_parent_path(self, parent_path: str) -> None:
        if not parent_path:
            return
        self.run_cli("workspace", "mkdirs", parent_path, json_output=False)

    def get_default_warehouse(self) -> str | None:
        data = self.run_cli("experimental", "aitools", "tools", "get-default-warehouse")
        if isinstance(data, dict):
            return data.get("warehouse_id") or data.get("id")
        return None

    # --- Genie Spaces CRUD ---

    def list_spaces(self) -> list[dict[str, Any]]:
        data = self.run_cli("genie", "list-spaces")
        if isinstance(data, dict):
            return data.get("spaces", [])
        if isinstance(data, list):
            return data
        return []

    def get_space(self, space_id: str, include_serialized_space: bool = True) -> dict[str, Any]:
        args = ["genie", "get-space", space_id]
        if include_serialized_space:
            args.append("--include-serialized-space")
        return self.run_cli(*args)

    def create_space(
        self,
        warehouse_id: str,
        serialized_space_compact: str,
        title: str,
        description: str = "",
        parent_path: str | None = None,
    ) -> dict[str, Any]:
        args = [
            "genie",
            "create-space",
            warehouse_id,
            serialized_space_compact,
            "--title",
            title,
        ]
        if description:
            args.extend(["--description", description])
        if parent_path:
            args.extend(["--parent-path", parent_path])
        return self.run_cli(*args)

    def update_space(
        self,
        space_id: str,
        serialized_space_compact: str,
        title: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        args = [
            "genie",
            "update-space",
            space_id,
            "--serialized-space",
            serialized_space_compact,
        ]
        if title:
            args.extend(["--title", title])
        if description:
            args.extend(["--description", description])
        return self.run_cli(*args)

    # --- Conversation API ---

    def start_conversation(self, space_id: str, question: str) -> dict[str, Any]:
        return self.run_cli("genie", "start-conversation", "--no-wait", space_id, question)

    def get_message(self, space_id: str, conversation_id: str, message_id: str) -> dict[str, Any]:
        return self.run_cli("genie", "get-message", space_id, conversation_id, message_id)

    def get_message_query_result(
        self,
        space_id: str,
        conversation_id: str,
        message_id: str,
        attachment_id: str,
    ) -> dict[str, Any]:
        return self.run_cli(
            "genie",
            "get-message-attachment-query-result",
            space_id,
            conversation_id,
            message_id,
            attachment_id,
        )

    def ask_and_wait(
        self,
        space_id: str,
        question: str,
        timeout_s: float = 180.0,
        poll_interval_s: float = 2.5,
    ) -> tuple[dict[str, Any], float]:
        """Envia pergunta via Conversation API e aguarda status terminal retornando (mensagem, latency_ms)."""
        start_ts = time.perf_counter()
        started = self.start_conversation(space_id, question)
        conv_id = started["conversation_id"]
        msg_id = started["message_id"]

        terminal = {"COMPLETED", "FAILED", "CANCELLED"}
        while True:
            msg = self.get_message(space_id, conv_id, msg_id)
            status = str(msg.get("status", "")).upper()
            if status in terminal:
                elapsed_ms = (time.perf_counter() - start_ts) * 1000.0
                return msg, elapsed_ms
            if (time.perf_counter() - start_ts) >= timeout_s:
                elapsed_ms = (time.perf_counter() - start_ts) * 1000.0
                return {
                    "status": "TIMEOUT",
                    "conversation_id": conv_id,
                    "message_id": msg_id,
                    "error": {"error": f"Timeout após {timeout_s:.0f}s aguardando resposta do Genie."},
                }, elapsed_ms
            time.sleep(poll_interval_s)

    # --- Native Eval Runs (Beta CLI) ---

    def create_eval_run(
        self,
        space_id: str,
        benchmark_question_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        body = {"benchmark_question_ids": benchmark_question_ids} if benchmark_question_ids else {}
        return self.run_cli(
            "genie",
            "genie-create-eval-run",
            space_id,
            "--json",
            json.dumps(body, separators=(",", ":")),
        )

    def get_eval_run(self, space_id: str, eval_run_id: str) -> dict[str, Any]:
        return self.run_cli("genie", "genie-get-eval-run", space_id, eval_run_id)

    def list_eval_results(self, space_id: str, eval_run_id: str) -> dict[str, Any]:
        return self.run_cli("genie", "genie-list-eval-results", space_id, eval_run_id)

    def get_eval_result_details(
        self, space_id: str, eval_run_id: str, result_id: str
    ) -> dict[str, Any]:
        return self.run_cli(
            "genie", "genie-get-eval-result-details", space_id, eval_run_id, result_id
        )

    # --- Conversations & Feedback Harvesting ---

    def list_conversations(self, space_id: str) -> list[dict[str, Any]]:
        data = self.run_cli("genie", "list-conversations", space_id)
        if isinstance(data, dict):
            return data.get("conversations", [])
        return data if isinstance(data, list) else []

    def list_conversation_messages(self, space_id: str, conversation_id: str) -> list[dict[str, Any]]:
        data = self.run_cli("genie", "list-conversation-messages", space_id, conversation_id)
        if isinstance(data, dict):
            return data.get("messages", [])
        return data if isinstance(data, list) else []

    # --- Read-Only SQL & Schema Discovery ---

    def discover_schema(self, identifiers: list[str]) -> Any:
        if not identifiers:
            return []
        return self.run_cli("experimental", "aitools", "tools", "discover-schema", *identifiers)

    def execute_readonly_sql(self, sql: str, warehouse_id: str | None = None) -> QueryResult:
        """Executa uma consulta estritamente read-only no SQL Warehouse via Databricks CLI."""
        assert_read_only_sql(sql)
        wh = warehouse_id or self.warehouse_id
        args = ["experimental", "aitools", "tools", "query"]
        if wh:
            args.extend(["--warehouse", wh])
        args.append(sql)
        raw = self.run_cli(*args)
        return parse_query_result(raw)

    def explain_sql(self, sql: str, warehouse_id: str | None = None) -> tuple[bool, str]:
        """Valida sintaxe e resolução de schema usando EXPLAIN read-only."""
        cleaned = sql.strip().rstrip(";")
        explain_stmt = cleaned if cleaned.upper().startswith("EXPLAIN") else f"EXPLAIN {cleaned}"
        try:
            self.execute_readonly_sql(explain_stmt, warehouse_id=warehouse_id)
            return True, "OK"
        except Exception as exc:
            return False, str(exc)

    def execute_uc_export_sql(
        self,
        sql: str,
        catalog: str,
        schema: str,
        warehouse_id: str | None = None,
    ) -> QueryResult:
        """
        Executa DDL/MERGE estritamente restrito às tabelas `genie_opt_*` de histórico
        no `<catalog>.<schema>` aprovado pelo usuário. Nunca substitui `execute_readonly_sql`.
        """
        from genieops.uc_export import assert_uc_export_sql_safe

        assert_uc_export_sql_safe(sql, catalog=catalog, schema=schema)
        wh = warehouse_id or self.warehouse_id
        args = ["experimental", "aitools", "tools", "query"]
        if wh:
            args.extend(["--warehouse", wh])
        args.append(sql)
        raw = self.run_cli(*args)
        return parse_query_result(raw)


def parse_query_result(raw: Any) -> QueryResult:
    """Normaliza diferentes formatos JSON de retorno da Databricks CLI para QueryResult."""
    if (
        isinstance(raw, list)
        and len(raw) == 1
        and isinstance(raw[0], dict)
        and any(k in raw[0] for k in ("statement_response", "manifest", "columns", "rows"))
    ):
        raw = raw[0]

    if isinstance(raw, dict):
        # Formato statement_response (Conversation API / SQL Execution API)
        sr = raw.get("statement_response", raw)
        manifest = sr.get("manifest", {})
        schema_cols = manifest.get("schema", {}).get("columns", [])
        if schema_cols:
            cols = [c.get("name", f"col_{i}") for i, c in enumerate(schema_cols)]
            rows = sr.get("result", {}).get("data_array", []) or []
            return QueryResult(columns=cols, rows=rows, raw=raw)

        # Formato aitools query: {"columns": [...], "rows": [...]} ou {"data": [...]}
        if "columns" in raw and "rows" in raw:
            cols = [
                c["name"] if isinstance(c, dict) else str(c) for c in raw["columns"]
            ]
            return QueryResult(columns=cols, rows=raw["rows"] or [], raw=raw)

        if "rows" in raw and isinstance(raw["rows"], list) and raw["rows"]:
            if isinstance(raw["rows"][0], dict):
                cols = list(raw["rows"][0].keys())
                rows = [[r.get(c) for c in cols] for r in raw["rows"]]
                return QueryResult(columns=cols, rows=rows, raw=raw)

    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        cols = list(raw[0].keys())
        rows = [[r.get(c) for c in cols] for r in raw]
        return QueryResult(columns=cols, rows=rows, raw=raw)

    return QueryResult(columns=[], rows=[], raw=raw)
