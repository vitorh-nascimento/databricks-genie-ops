"""Compilador determinístico Genie-as-Code -> serialized_space v2, parser reverso (pull) e diff."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from genieops.models import (
    HEX_32_RE,
    BenchmarkCase,
    BenchmarksConfig,
    ColumnConfig,
    EnvironmentConfig,
    ExampleQuestionSql,
    InstructionsConfig,
    JoinEndpoint,
    JoinSpec,
    SampleQuestion,
    SourcesConfig,
    SpaceBundle,
    SpaceConfig,
    SqlFunction,
    SqlSnippetExpression,
    SqlSnippetFilter,
    SqlSnippetMeasure,
    SqlSnippetsConfig,
    TableSource,
    VolumeSource,
)

# Namespace UUID fixo do framework para garantir IDs 32-hex 100% determinísticos
GENIEOPS_NAMESPACE = uuid.UUID("c6f42891-9e14-4d62-8b9f-7a0d93e41b25")

RELATIONSHIP_TAG_PREFIX = "--rt=FROM_RELATIONSHIP_TYPE_"
RELATIONSHIP_TAG_SUFFIX = "--"
RELATIONSHIP_TAG_RE = re.compile(
    r"--rt=FROM_RELATIONSHIP_TYPE_(ONE_TO_MANY|MANY_TO_ONE|ONE_TO_ONE|MANY_TO_MANY)--"
)


def deterministic_hex_id(
    space_name: str,
    surface: str,
    seed: str,
    used_ids: set[str],
    explicit_id: str | None = None,
) -> str:
    """
    Gera um ID hexadecimal de 32 caracteres minúsculos determinístico e único.
    Se `explicit_id` já for um 32-hex válido e ainda não utilizado, preserva-o (round-trip fiel).
    """
    if explicit_id and HEX_32_RE.match(explicit_id) and explicit_id not in used_ids:
        used_ids.add(explicit_id)
        return explicit_id

    salt = 0
    while True:
        key = f"{space_name}|{surface}|{seed}" if salt == 0 else f"{space_name}|{surface}|{seed}|{salt}"
        candidate = uuid.uuid5(GENIEOPS_NAMESPACE, key).hex
        if candidate not in used_ids:
            used_ids.add(candidate)
            return candidate
        salt += 1


def flatten_sql(sql: str) -> str:
    """Normaliza quebras de linha em SQL para uma única linha limpa compatível com serialized_space."""
    return " ".join(line.strip() for line in sql.strip().splitlines() if line.strip())


def _compile_column_config(col: ColumnConfig) -> dict[str, Any]:
    entry: dict[str, Any] = {"column_name": col.column_name}
    if col.description:
        entry["description"] = list(col.description)
    if col.synonyms:
        entry["synonyms"] = sorted(dict.fromkeys(col.synonyms))
    if col.enable_format_assistance is not None:
        entry["enable_format_assistance"] = col.enable_format_assistance
    if col.enable_entity_matching is not None:
        entry["enable_entity_matching"] = col.enable_entity_matching
    if col.exclude is not None:
        entry["exclude"] = col.exclude
    return entry


def _compile_table_source(src: TableSource) -> dict[str, Any]:
    entry: dict[str, Any] = {"identifier": src.identifier}
    if src.description:
        entry["description"] = list(src.description)
    if src.column_configs:
        entry["column_configs"] = sorted(
            [_compile_column_config(c) for c in src.column_configs],
            key=lambda c: c["column_name"],
        )
    return entry


def compile_space(bundle: SpaceBundle, *, expand_paraphrases: bool = False) -> dict[str, Any]:
    """
    Compila um SpaceBundle declarativo para o objeto JSON oficial `serialized_space` v2
    com ordenação estável de chaves/arrays e IDs 32-hex determinísticos.
    Quando `expand_paraphrases=True`, inclui as paráfrases de cada benchmark como casos adicionais.
    """
    space_name = bundle.space.name
    used_question_ids: set[str] = set()
    used_instruction_ids: set[str] = set()

    payload: dict[str, Any] = {"version": 2}

    # 1. config.sample_questions
    if bundle.instructions.sample_questions:
        sq_items = []
        for idx, sq in enumerate(bundle.instructions.sample_questions):
            sq_id = deterministic_hex_id(
                space_name,
                "sample_question",
                sq.question.strip() or str(idx),
                used_question_ids,
                explicit_id=sq.id,
            )
            sq_items.append({"id": sq_id, "question": [sq.question.strip()]})
        payload["config"] = {
            "sample_questions": sorted(sq_items, key=lambda x: x["id"]),
        }

    # 2. data_sources (tables, metric_views, volumes)
    data_sources: dict[str, Any] = {}
    if bundle.sources.tables:
        data_sources["tables"] = sorted(
            [_compile_table_source(t) for t in bundle.sources.tables],
            key=lambda t: t["identifier"],
        )
    if bundle.sources.metric_views:
        data_sources["metric_views"] = sorted(
            [_compile_table_source(mv) for mv in bundle.sources.metric_views],
            key=lambda mv: mv["identifier"],
        )
    if bundle.sources.volumes:
        vols = []
        for v in bundle.sources.volumes:
            ventry: dict[str, Any] = {"path": v.path}
            if v.description:
                ventry["description"] = list(v.description)
            vols.append(ventry)
        data_sources["volumes"] = sorted(vols, key=lambda v: v["path"])
    payload["data_sources"] = data_sources

    # 3. instructions
    instructions: dict[str, Any] = {}

    if bundle.instructions.text_instructions:
        ti_id = deterministic_hex_id(
            space_name,
            "text_instruction",
            "global_instructions",
            used_instruction_ids,
            explicit_id=bundle.instructions.text_instruction_id,
        )
        instructions["text_instructions"] = [
            {"id": ti_id, "content": list(bundle.instructions.text_instructions)}
        ]

    if bundle.instructions.example_question_sqls:
        ex_items = []
        for ex in bundle.instructions.example_question_sqls:
            ex_id = deterministic_hex_id(
                space_name,
                "example_sql",
                ex.question.strip(),
                used_instruction_ids,
                explicit_id=ex.id,
            )
            ex_items.append(
                {
                    "id": ex_id,
                    "question": [ex.question.strip()],
                    "sql": [flatten_sql(ex.sql)],
                }
            )
        instructions["example_question_sqls"] = sorted(ex_items, key=lambda x: x["id"])

    if bundle.instructions.join_specs:
        js_items = []
        for js in bundle.instructions.join_specs:
            seed = f"{js.left.identifier}:{js.left.alias}={js.right.identifier}:{js.right.alias}|{js.condition}"
            js_id = deterministic_hex_id(
                space_name,
                "join_spec",
                seed,
                used_instruction_ids,
                explicit_id=js.id,
            )
            rel_tag = f"{RELATIONSHIP_TAG_PREFIX}{js.relationship_type}{RELATIONSHIP_TAG_SUFFIX}"
            js_items.append(
                {
                    "id": js_id,
                    "left": {"identifier": js.left.identifier, "alias": js.left.alias},
                    "right": {"identifier": js.right.identifier, "alias": js.right.alias},
                    "sql": [flatten_sql(js.condition), rel_tag],
                }
            )
        instructions["join_specs"] = sorted(js_items, key=lambda x: x["id"])

    snippets_out: dict[str, Any] = {}
    if bundle.instructions.sql_snippets.measures:
        items = []
        for m in bundle.instructions.sql_snippets.measures:
            m_id = deterministic_hex_id(
                space_name,
                "snippet_measure",
                f"{m.alias}:{m.display_name}",
                used_instruction_ids,
                explicit_id=m.id,
            )
            entry: dict[str, Any] = {
                "id": m_id,
                "alias": m.alias,
                "display_name": m.display_name,
                "sql": [flatten_sql(m.sql)],
            }
            if m.synonyms:
                entry["synonyms"] = sorted(dict.fromkeys(m.synonyms))
            items.append(entry)
        snippets_out["measures"] = sorted(items, key=lambda x: x["id"])

    if bundle.instructions.sql_snippets.filters:
        items = []
        for f in bundle.instructions.sql_snippets.filters:
            f_id = deterministic_hex_id(
                space_name,
                "snippet_filter",
                f"{f.display_name}:{f.sql}",
                used_instruction_ids,
                explicit_id=f.id,
            )
            entry = {
                "id": f_id,
                "display_name": f.display_name,
                "sql": [flatten_sql(f.sql)],
            }
            if f.synonyms:
                entry["synonyms"] = sorted(dict.fromkeys(f.synonyms))
            items.append(entry)
        snippets_out["filters"] = sorted(items, key=lambda x: x["id"])

    if bundle.instructions.sql_snippets.expressions:
        items = []
        for e in bundle.instructions.sql_snippets.expressions:
            e_id = deterministic_hex_id(
                space_name,
                "snippet_expression",
                f"{e.alias}:{e.display_name}",
                used_instruction_ids,
                explicit_id=e.id,
            )
            entry = {
                "id": e_id,
                "alias": e.alias,
                "display_name": e.display_name,
                "sql": [flatten_sql(e.sql)],
            }
            if e.synonyms:
                entry["synonyms"] = sorted(dict.fromkeys(e.synonyms))
            items.append(entry)
        snippets_out["expressions"] = sorted(items, key=lambda x: x["id"])

    if snippets_out:
        instructions["sql_snippets"] = snippets_out

    if bundle.instructions.sql_functions:
        fn_items = []
        for fn in bundle.instructions.sql_functions:
            fn_id = deterministic_hex_id(
                space_name,
                "sql_function",
                fn.identifier.strip(),
                used_instruction_ids,
                explicit_id=fn.id,
            )
            fn_items.append({"id": fn_id, "identifier": fn.identifier.strip()})
        instructions["sql_functions"] = sorted(
            fn_items, key=lambda x: (x["id"], x["identifier"])
        )

    if instructions:
        payload["instructions"] = instructions

    # 4. benchmarks (top-level, nunca dentro de instructions!)
    if bundle.benchmarks.questions:
        bmk_items = []
        for bmk in bundle.benchmarks.questions:
            bmk_id = deterministic_hex_id(
                space_name,
                "benchmark",
                bmk.id or bmk.question.strip(),
                used_question_ids,
                explicit_id=bmk.id,
            )
            sql_content = [flatten_sql(bmk.ground_truth_sql)] if bmk.ground_truth_sql else []
            item: dict[str, Any] = {
                "id": bmk_id,
                "question": [bmk.question.strip()],
                "answer": [{"format": "SQL", "content": sql_content}],
            }
            if bmk.evaluation_note:
                item["evaluation_note"] = [bmk.evaluation_note.strip()]
            bmk_items.append(item)

            if expand_paraphrases and bmk.paraphrases:
                base_seed = bmk.id or bmk.question.strip()
                for p_idx, para in enumerate(bmk.paraphrases, start=1):
                    para_clean = para.strip()
                    if not para_clean:
                        continue
                    para_id = deterministic_hex_id(
                        space_name,
                        "benchmark_paraphrase",
                        f"{base_seed}::p{p_idx}::{para_clean}",
                        used_question_ids,
                    )
                    p_item: dict[str, Any] = {
                        "id": para_id,
                        "question": [para_clean],
                        "answer": [{"format": "SQL", "content": sql_content}],
                    }
                    if bmk.evaluation_note:
                        p_item["evaluation_note"] = [bmk.evaluation_note.strip()]
                    bmk_items.append(p_item)
        payload["benchmarks"] = {"questions": sorted(bmk_items, key=lambda x: x["id"])}

    return payload


def serialize_compact(payload: dict[str, Any]) -> str:
    """Serializa o payload para string JSON compacta pronta para a Databricks CLI."""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def payload_hash(payload: dict[str, Any]) -> str:
    """Calcula SHA-256 curto (12 chars) do payload compilado para rastreamento de versões."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _join_text_array(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    return str(value or "")


def parse_serialized_space(
    remote_response: dict[str, Any],
    space_name: str,
    env_name: str = "dev",
    profile: str | None = None,
) -> SpaceBundle:
    """
    Converte a resposta de `databricks genie get-space --include-serialized-space -o json`
    (ou um objeto `serialized_space` já desempacotado) para um SpaceBundle declarativo.
    """
    if "serialized_space" in remote_response:
        raw_ss = remote_response["serialized_space"]
        ss = json.loads(raw_ss) if isinstance(raw_ss, str) else raw_ss
        title = remote_response.get("title") or space_name
        description = remote_response.get("description") or ""
        space_id = remote_response.get("space_id")
        warehouse_id = remote_response.get("warehouse_id")
        parent_path = remote_response.get("parent_path")
    else:
        ss = remote_response
        title = space_name
        description = ""
        space_id = None
        warehouse_id = None
        parent_path = None

    # Detecta catalog/schema principal a partir da primeira tabela ou metric view
    ds = ss.get("data_sources", {})
    raw_tables = ds.get("tables", [])
    raw_mvs = ds.get("metric_views", [])
    raw_vols = ds.get("volumes", [])

    inferred_catalog: str | None = None
    inferred_schema: str | None = None
    first_source = (raw_tables + raw_mvs)[0] if (raw_tables or raw_mvs) else None
    if first_source and "." in first_source.get("identifier", ""):
        parts = first_source["identifier"].split(".")
        if len(parts) >= 3:
            inferred_catalog, inferred_schema = parts[0], parts[1]

    def _parse_table(raw: dict[str, Any]) -> TableSource:
        cols = [
            ColumnConfig(
                column_name=c["column_name"],
                description=c.get("description", []),
                synonyms=c.get("synonyms", []),
                enable_entity_matching=c.get("enable_entity_matching"),
                enable_format_assistance=c.get("enable_format_assistance"),
                exclude=c.get("exclude"),
            )
            for c in raw.get("column_configs", [])
        ]
        return TableSource(
            identifier=raw["identifier"],
            description=raw.get("description", []),
            column_configs=cols,
        )

    sources = SourcesConfig(
        tables=[_parse_table(t) for t in raw_tables],
        metric_views=[_parse_table(mv) for mv in raw_mvs],
        volumes=[
            VolumeSource(path=v["path"], description=v.get("description", []))
            for v in raw_vols
        ],
    )

    # config.sample_questions
    sample_questions = [
        SampleQuestion(id=sq.get("id"), question=_join_text_array(sq.get("question", [])))
        for sq in ss.get("config", {}).get("sample_questions", [])
    ]

    # instructions
    raw_inst = ss.get("instructions", {})
    text_instructions: list[str] = []
    text_instruction_id: str | None = None
    if raw_inst.get("text_instructions"):
        first_ti = raw_inst["text_instructions"][0]
        text_instruction_id = first_ti.get("id")
        text_instructions = list(first_ti.get("content", []))

    example_sqls = [
        ExampleQuestionSql(
            id=ex.get("id"),
            question=_join_text_array(ex.get("question", [])),
            sql=_join_text_array(ex.get("sql", [])),
        )
        for ex in raw_inst.get("example_question_sqls", [])
    ]

    join_specs: list[JoinSpec] = []
    for js in raw_inst.get("join_specs", []):
        sql_arr = js.get("sql", [])
        cond = sql_arr[0] if sql_arr else ""
        rel_type = "ONE_TO_MANY"
        for item in sql_arr[1:]:
            match = RELATIONSHIP_TAG_RE.search(str(item))
            if match:
                rel_type = match.group(1)
                break
        join_specs.append(
            JoinSpec(
                id=js.get("id"),
                left=JoinEndpoint(
                    identifier=js["left"]["identifier"],
                    alias=js["left"]["alias"],
                ),
                right=JoinEndpoint(
                    identifier=js["right"]["identifier"],
                    alias=js["right"]["alias"],
                ),
                condition=cond,
                relationship_type=rel_type,  # type: ignore[arg-type]
            )
        )

    raw_snip = raw_inst.get("sql_snippets", {})
    sql_snippets = SqlSnippetsConfig(
        measures=[
            SqlSnippetMeasure(
                id=m.get("id"),
                alias=m["alias"],
                display_name=m["display_name"],
                sql=_join_text_array(m.get("sql", [])),
                synonyms=m.get("synonyms", []),
            )
            for m in raw_snip.get("measures", [])
        ],
        filters=[
            SqlSnippetFilter(
                id=f.get("id"),
                display_name=f["display_name"],
                sql=_join_text_array(f.get("sql", [])),
                synonyms=f.get("synonyms", []),
            )
            for f in raw_snip.get("filters", [])
        ],
        expressions=[
            SqlSnippetExpression(
                id=e.get("id"),
                alias=e["alias"],
                display_name=e["display_name"],
                sql=_join_text_array(e.get("sql", [])),
                synonyms=e.get("synonyms", []),
            )
            for e in raw_snip.get("expressions", [])
        ],
    )

    sql_functions = [
        SqlFunction(
            id=fn.get("id"),
            identifier=fn["identifier"],
        )
        for fn in raw_inst.get("sql_functions", [])
        if isinstance(fn, dict) and fn.get("identifier")
    ]

    instructions = InstructionsConfig(
        join_specs=join_specs,
        sql_snippets=sql_snippets,
        sql_functions=sql_functions,
        example_question_sqls=example_sqls,
        text_instructions=text_instructions,
        text_instruction_id=text_instruction_id,
        sample_questions=sample_questions,
    )

    # benchmarks
    bmk_questions: list[BenchmarkCase] = []
    for bq in ss.get("benchmarks", {}).get("questions", []):
        answers = bq.get("answer", [])
        sql_str: str | None = None
        if answers and isinstance(answers, list):
            content = answers[0].get("content", [])
            if content:
                sql_str = _join_text_array(content)
        eval_note_arr = bq.get("evaluation_note")
        eval_note = _join_text_array(eval_note_arr) if eval_note_arr else None
        mode = "agent" if (not sql_str and eval_note) else "chat"
        bmk_questions.append(
            BenchmarkCase(
                id=bq.get("id"),
                question=_join_text_array(bq.get("question", [])),
                ground_truth_sql=sql_str,
                mode=mode,  # type: ignore[arg-type]
                evaluation_note=eval_note,
            )
        )

    env_cfg = EnvironmentConfig(
        name=env_name,
        profile=profile,
        warehouse_id=warehouse_id,
        catalog=inferred_catalog,
        schema=inferred_schema,
        parent_path=parent_path,
        space_id=space_id,
    )

    return SpaceBundle(
        space=SpaceConfig(
            name=space_name,
            title=title,
            description=description,
            default_env=env_name,
            environments={env_name: env_cfg},
        ),
        sources=sources,
        instructions=instructions,
        benchmarks=BenchmarksConfig(questions=bmk_questions),
    )


@dataclass
class PayloadDiff:
    """Resultado da comparação entre payload local compilado e remoto."""

    has_changes: bool
    unified_diff: str
    summary: list[str] = field(default_factory=list)


def diff_payloads(local_payload: dict[str, Any], remote_payload: dict[str, Any]) -> PayloadDiff:
    """Compara dois payloads `serialized_space` v2 e gera resumo estruturado + unified diff."""
    local_str = json.dumps(local_payload, indent=2, sort_keys=True, ensure_ascii=False)
    remote_str = json.dumps(remote_payload, indent=2, sort_keys=True, ensure_ascii=False)

    if local_str == remote_str:
        return PayloadDiff(has_changes=False, unified_diff="", summary=["Sem alterações."])

    diff_lines = list(
        difflib.unified_diff(
            remote_str.splitlines(),
            local_str.splitlines(),
            fromfile="remote/serialized_space.json",
            tofile="local/serialized_space.json",
            lineterm="",
        )
    )

    summary: list[str] = []
    local_ds = local_payload.get("data_sources", {})
    remote_ds = remote_payload.get("data_sources", {})

    for key in ("tables", "metric_views"):
        l_ids = {t["identifier"] for t in local_ds.get(key, [])}
        r_ids = {t["identifier"] for t in remote_ds.get(key, [])}
        for added in sorted(l_ids - r_ids):
            summary.append(f"+ {key}: {added}")
        for removed in sorted(r_ids - l_ids):
            summary.append(f"- {key}: {removed}")

    l_vols = {v["path"] for v in local_ds.get("volumes", [])}
    r_vols = {v["path"] for v in remote_ds.get("volumes", [])}
    for added in sorted(l_vols - r_vols):
        summary.append(f"+ volumes: {added}")
    for removed in sorted(r_vols - l_vols):
        summary.append(f"- volumes: {removed}")

    l_inst = local_payload.get("instructions", {})
    r_inst = remote_payload.get("instructions", {})
    for key in ("text_instructions", "example_question_sqls", "join_specs", "sql_functions"):
        if l_inst.get(key) != r_inst.get(key):
            l_len = len(l_inst.get(key, []))
            r_len = len(r_inst.get(key, []))
            summary.append(f"~ instructions.{key}: remoto={r_len} -> local={l_len}")

    if l_inst.get("sql_snippets") != r_inst.get("sql_snippets"):
        summary.append("~ instructions.sql_snippets alterado")

    l_bmk = len(local_payload.get("benchmarks", {}).get("questions", []))
    r_bmk = len(remote_payload.get("benchmarks", {}).get("questions", []))
    if local_payload.get("benchmarks") != remote_payload.get("benchmarks"):
        summary.append(f"~ benchmarks.questions: remoto={r_bmk} -> local={l_bmk}")

    if not summary:
        summary.append("~ Metadados internos ou column_configs alterados")

    return PayloadDiff(
        has_changes=True,
        unified_diff="\n".join(diff_lines),
        summary=summary,
    )
