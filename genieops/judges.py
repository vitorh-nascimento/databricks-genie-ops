"""Avaliadores LLM-as-a-Judge plugáveis para benchmarks Agent Mode e síntese analítica."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

from genieops.agent_mode import resolve_databricks_auth
from genieops.models import BenchmarkCase

JudgeProviderName = Literal["heuristic", "databricks", "openai"]


@dataclass
class JudgeVerdict:
    """Resultado estruturado da avaliação de uma resposta do Genie Agent."""

    passed: bool
    score: float  # 0.0 .. 100.0
    reasoning: str
    provider: str
    model: str
    criteria_checks: list[dict[str, Any]] = field(default_factory=list)


class JudgeProvider(Protocol):
    """Interface plugável para qualquer avaliador (heurístico, Databricks FMAPI ou OpenAI-compatible)."""

    provider_name: str
    model_name: str

    def evaluate(
        self,
        case: BenchmarkCase,
        answer_text: str,
        executed_sqls: list[str] | None = None,
        reasoning_steps: list[str] | None = None,
        citations: list[dict[str, str]] | None = None,
    ) -> JudgeVerdict: ...


def _build_judge_prompt(
    case: BenchmarkCase,
    answer_text: str,
    executed_sqls: list[str],
    reasoning_steps: list[str],
    citations: list[dict[str, str]],
) -> str:
    criteria_lines = list(case.semantic_criteria)
    if case.evaluation_note:
        criteria_lines.insert(0, f"Nota oficial de avaliação: {case.evaluation_note}")
    if case.expected_tables:
        criteria_lines.append(f"Fontes esperadas: {', '.join(case.expected_tables)}")

    criteria_block = "\n".join(f"- {c}" for c in criteria_lines) or "- Resposta factual, clara e fundamentada."
    sql_block = "\n\n".join(executed_sqls) if executed_sqls else "(nenhum SQL executado)"
    cit_block = ", ".join(c.get("url", "") for c in citations) if citations else "(nenhuma citação)"

    return (
        "Você é um avaliador rigoroso de qualidade de Databricks Genie Agents.\n"
        "Avalie se a resposta do agente atende integralmente aos critérios do benchmark.\n"
        "Responda EXCLUSIVAMENTE em JSON válido com as chaves:\n"
        '{"passed": true|false, "score": 0..100, "reasoning": "explicação objetiva em PT-BR", '
        '"criteria_checks": [{"criterion": "...", "passed": true|false}]}\n\n'
        f"PERGUNTA:\n{case.question}\n\n"
        f"CRITÉRIOS DE AVALIAÇÃO:\n{criteria_block}\n\n"
        f"SQLs EXECUTADOS PELO AGENTE:\n{sql_block}\n\n"
        f"CITAÇÕES:\n{cit_block}\n\n"
        f"PASSOS DE RACIOCÍNIO ({len(reasoning_steps)}):\n"
        + ("\n".join(f"- {s}" for s in reasoning_steps[:5]) if reasoning_steps else "(não informado)")
        + f"\n\nRESPOSTA FINAL DO AGENTE:\n{answer_text or '(vazia)'}"
    )


def _parse_judge_json(raw_text: str, provider: str, model: str) -> JudgeVerdict:
    cleaned = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1)
    else:
        brace_start = cleaned.find("{")
        brace_end = cleaned.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            cleaned = cleaned[brace_start : brace_end + 1]

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return JudgeVerdict(
            passed=False,
            score=0.0,
            reasoning=f"Resposta do juiz fora do formato JSON esperado: {raw_text[:200]}",
            provider=provider,
            model=model,
        )

    passed = bool(parsed.get("passed", False))
    score = float(parsed.get("score", 100.0 if passed else 0.0))
    score = max(0.0, min(100.0, score))
    reasoning = str(parsed.get("reasoning") or "Sem justificativa informada.")
    checks = parsed.get("criteria_checks") if isinstance(parsed.get("criteria_checks"), list) else []
    return JudgeVerdict(
        passed=passed,
        score=score,
        reasoning=reasoning,
        provider=provider,
        model=model,
        criteria_checks=checks,
    )


class HeuristicRubricJudge:
    """
    Avaliador determinístico local (custo zero) baseado em rubrica objetiva:
    útil para testes offline, CI e triagem inicial de respostas Agent Mode.
    """

    provider_name = "heuristic"
    model_name = "rubric-v1"

    def evaluate(
        self,
        case: BenchmarkCase,
        answer_text: str,
        executed_sqls: list[str] | None = None,
        reasoning_steps: list[str] | None = None,
        citations: list[dict[str, str]] | None = None,
    ) -> JudgeVerdict:
        sqls = executed_sqls or []
        cits = citations or []
        checks: list[dict[str, Any]] = []

        # 1. Resposta substantiva
        has_answer = bool(answer_text and len(answer_text.strip()) >= 25)
        checks.append({"criterion": "Resposta final não vazia e substantiva", "passed": has_answer})

        # 2. Fontes esperadas (se definidas e houver SQL)
        if case.expected_tables:
            joined_sql = " ".join(sqls).lower()
            src_ok = any(
                t.lower() in joined_sql or t.split(".")[-1].lower() in joined_sql
                for t in case.expected_tables
            )
            checks.append(
                {"criterion": f"Uso de fonte esperada ({', '.join(case.expected_tables)})", "passed": src_ok}
            )

        # 3. Citações de documentos quando a nota exige referência documental
        note_low = (case.evaluation_note or "").lower()
        if any(k in note_low for k in ("citar", "documento", "política", "volume", "pdf", "cite")):
            doc_ok = bool(cits) or any(
                k in answer_text.lower() for k in ("política", "manual", "documento", "volume", "regra")
            )
            checks.append({"criterion": "Referência ou citação documental presente", "passed": doc_ok})

        # 4. Critérios semânticos declarados (correspondência por palavras-chave relevantes >= 4 chars)
        answer_plus_sql = f"{answer_text} {' '.join(sqls)}".lower()
        stopwords = {
            "para", "como", "deve", "deverá", "sobre", "entre", "com", "sem", "pelo", "pela",
            "must", "with", "from", "that", "this", "using", "include", "resposta", "dados",
        }
        for crit in case.semantic_criteria:
            tokens = [
                t for t in re.findall(r"[a-zà-ú0-9_]{4,}", crit.lower()) if t not in stopwords
            ]
            if not tokens:
                continue
            hits = sum(1 for tok in tokens if tok in answer_plus_sql)
            crit_ok = hits >= max(1, len(tokens) // 3)
            checks.append({"criterion": crit, "passed": crit_ok})

        total = len(checks)
        passed_cnt = sum(1 for c in checks if c["passed"])
        score = round((passed_cnt / total) * 100.0, 2) if total else 0.0
        overall_pass = has_answer and score >= 70.0
        failed_names = [c["criterion"] for c in checks if not c["passed"]]
        reason = (
            f"Rubrica heurística aprovada ({passed_cnt}/{total} critérios atendidos)."
            if overall_pass
            else f"Rubrica heurística reprovada ({passed_cnt}/{total}): faltou {'; '.join(failed_names)}."
        )
        return JudgeVerdict(
            passed=overall_pass,
            score=score,
            reasoning=reason,
            provider=self.provider_name,
            model=self.model_name,
            criteria_checks=checks,
        )


class DatabricksFoundationModelJudge:
    """
    LLM-as-a-Judge via Databricks Foundation Model API / Unity Gateway (`/serving-endpoints/<endpoint>/invocations`).
    Autentica via perfil Databricks CLI — zero segredos hardcoded.
    """

    provider_name = "databricks"

    def __init__(
        self,
        endpoint: str | None = None,
        profile: str | None = None,
        host: str | None = None,
        token: str | None = None,
        timeout_s: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        cli_runner: Any = None,
    ) -> None:
        self.model_name = (
            endpoint
            or os.environ.get("GENIEOPS_JUDGE_ENDPOINT")
            or "databricks-meta-llama-3-3-70b-instruct"
        )
        self.profile = profile
        self._host = host
        self._token = token
        self.timeout_s = timeout_s
        self._transport = transport
        self._cli_runner = cli_runner

    def evaluate(
        self,
        case: BenchmarkCase,
        answer_text: str,
        executed_sqls: list[str] | None = None,
        reasoning_steps: list[str] | None = None,
        citations: list[dict[str, str]] | None = None,
    ) -> JudgeVerdict:
        host, token = resolve_databricks_auth(
            profile=self.profile,
            host=self._host,
            token=self._token,
            runner=self._cli_runner,
        )
        url = f"{host}/serving-endpoints/{self.model_name}/invocations"
        prompt = _build_judge_prompt(
            case, answer_text, executed_sqls or [], reasoning_steps or [], citations or []
        )
        payload = {
            "messages": [
                {"role": "system", "content": "Responda exclusivamente em JSON válido."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 600,
        }
        client_kwargs: dict[str, Any] = {"timeout": httpx.Timeout(self.timeout_s)}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport

        with httpx.Client(**client_kwargs) as client:
            resp = client.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices") or []
        content = ""
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get("message") or {}
            content = str(msg.get("content") or choices[0].get("text") or "")
        return _parse_judge_json(content, provider=self.provider_name, model=self.model_name)


class OpenAICompatibleJudge:
    """
    LLM-as-a-Judge compatível com qualquer API OpenAI (`/chat/completions`).
    Lê configuração exclusivamente de variáveis de ambiente (`GENIEOPS_JUDGE_*`).
    """

    provider_name = "openai"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_s: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("GENIEOPS_JUDGE_BASE_URL") or "https://api.openai.com/v1"
        ).rstrip("/")
        self.api_key = api_key or os.environ.get("GENIEOPS_JUDGE_API_KEY") or ""
        self.model_name = model or os.environ.get("GENIEOPS_JUDGE_MODEL") or "gpt-4o-mini"
        self.timeout_s = timeout_s
        self._transport = transport

    def evaluate(
        self,
        case: BenchmarkCase,
        answer_text: str,
        executed_sqls: list[str] | None = None,
        reasoning_steps: list[str] | None = None,
        citations: list[dict[str, str]] | None = None,
    ) -> JudgeVerdict:
        if not self.api_key:
            raise ValueError(
                "GENIEOPS_JUDGE_API_KEY não configurada para o provedor 'openai'."
            )
        url = f"{self.base_url}/chat/completions"
        prompt = _build_judge_prompt(
            case, answer_text, executed_sqls or [], reasoning_steps or [], citations or []
        )
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": "Responda exclusivamente em JSON válido."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
        }
        client_kwargs: dict[str, Any] = {"timeout": httpx.Timeout(self.timeout_s)}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport

        with httpx.Client(**client_kwargs) as client:
            resp = client.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices") or []
        content = str((choices[0].get("message") or {}).get("content") or "") if choices else ""
        return _parse_judge_json(content, provider=self.provider_name, model=self.model_name)


class CallableJudgeAdapter:
    """Adaptador para funções Python customizadas (`(case, answer_text, sql) -> (bool, str)`)."""

    provider_name = "custom"
    model_name = "callable"

    def __init__(self, fn: Callable[[BenchmarkCase, str, str | None], tuple[bool, str]]) -> None:
        self._fn = fn

    def evaluate(
        self,
        case: BenchmarkCase,
        answer_text: str,
        executed_sqls: list[str] | None = None,
        reasoning_steps: list[str] | None = None,
        citations: list[dict[str, str]] | None = None,
    ) -> JudgeVerdict:
        first_sql = executed_sqls[0] if executed_sqls else None
        ok, note = self._fn(case, answer_text, first_sql)
        return JudgeVerdict(
            passed=bool(ok),
            score=100.0 if ok else 0.0,
            reasoning=str(note),
            provider=self.provider_name,
            model=self.model_name,
        )


def create_judge(
    provider: JudgeProviderName = "heuristic",
    *,
    profile: str | None = None,
    endpoint: str | None = None,
    model: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> JudgeProvider:
    """Instancia o provedor LLM-as-a-Judge solicitado."""
    if provider == "heuristic":
        return HeuristicRubricJudge()
    if provider == "databricks":
        return DatabricksFoundationModelJudge(
            endpoint=endpoint or model,
            profile=profile,
            transport=transport,
        )
    if provider == "openai":
        return OpenAICompatibleJudge(model=model, transport=transport)
    raise ValueError(f"Provedor de juiz desconhecido: {provider}")
