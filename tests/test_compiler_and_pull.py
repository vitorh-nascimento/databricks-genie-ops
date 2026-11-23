"""Testes do compilador determinístico serialized_space v2 e do round-trip pull -> compile."""

from __future__ import annotations

import json
from pathlib import Path

from genieops.compiler import compile_space, parse_serialized_space
from genieops.loader import load_space, save_space
from genieops.models import HEX_32_RE, SpaceBundle


def test_compile_is_deterministic_and_follows_v2_schema(exemplo_bundle: SpaceBundle) -> None:
    p1 = compile_space(exemplo_bundle)
    p2 = compile_space(exemplo_bundle)

    assert json.dumps(p1, sort_keys=False) == json.dumps(p2, sort_keys=False)
    assert p1["version"] == 2
    assert "benchmarks" in p1
    assert "benchmarks" not in p1.get("instructions", {})

    # Ordenação obrigatória de tabelas, metric_views, volumes e column_configs
    tables = p1["data_sources"]["tables"]
    assert [t["identifier"] for t in tables] == sorted(t["identifier"] for t in tables)
    for t in tables:
        col_names = [c["column_name"] for c in t.get("column_configs", [])]
        assert col_names == sorted(col_names)

    mvs = p1["data_sources"]["metric_views"]
    assert [m["identifier"] for m in mvs] == sorted(m["identifier"] for m in mvs)
    vols = p1["data_sources"]["volumes"]
    assert [v["path"] for v in vols] == sorted(v["path"] for v in vols)

    # text_instructions <= 1 bloco e arrays de strings
    ti = p1["instructions"]["text_instructions"]
    assert len(ti) == 1
    assert isinstance(ti[0]["content"], list)
    assert HEX_32_RE.match(ti[0]["id"])

    # Unicidade de IDs em perguntas (sample_questions + benchmarks) e instruções
    sq_ids = [q["id"] for q in p1["config"]["sample_questions"]]
    bmk_ids = [q["id"] for q in p1["benchmarks"]["questions"]]
    assert sq_ids == sorted(sq_ids)
    assert bmk_ids == sorted(bmk_ids)
    assert len(sq_ids + bmk_ids) == len(set(sq_ids + bmk_ids))
    assert all(HEX_32_RE.match(i) for i in sq_ids + bmk_ids)

    inst = p1["instructions"]
    inst_ids = (
        [x["id"] for x in inst.get("text_instructions", [])]
        + [x["id"] for x in inst.get("example_question_sqls", [])]
        + [x["id"] for x in inst.get("join_specs", [])]
        + [x["id"] for x in inst.get("sql_functions", [])]
        + [x["id"] for x in inst.get("sql_snippets", {}).get("measures", [])]
        + [x["id"] for x in inst.get("sql_snippets", {}).get("filters", [])]
        + [x["id"] for x in inst.get("sql_snippets", {}).get("expressions", [])]
    )
    assert len(inst_ids) == len(set(inst_ids))
    assert all(HEX_32_RE.match(i) for i in inst_ids)
    assert len(inst.get("sql_functions", [])) == 3

    # Agent mode benchmark tem content: [] e evaluation_note como array
    agent_bmks = [b for b in p1["benchmarks"]["questions"] if not b["answer"][0]["content"]]
    assert len(agent_bmks) == 2
    for ab in agent_bmks:
        assert ab["answer"] == [{"format": "SQL", "content": []}]
        assert isinstance(ab["evaluation_note"], list) and len(ab["evaluation_note"]) == 1


def test_pull_parse_save_load_compile_roundtrip(
    exemplo_bundle: SpaceBundle, tmp_path: Path
) -> None:
    original_compiled = compile_space(exemplo_bundle)
    remote_api_response = {
        "space_id": "01ef9999000011112222333344445555",
        "title": exemplo_bundle.space.title,
        "description": exemplo_bundle.space.description,
        "warehouse_id": "wh_demo_123",
        "parent_path": "/Workspace/Shared/genie_spaces/dev",
        "serialized_space": json.dumps(original_compiled, ensure_ascii=False),
    }

    parsed = parse_serialized_space(
        remote_api_response,
        space_name="pulled_vendas",
        env_name="dev",
        profile="dev-profile",
    )
    save_space(parsed, base_dir=tmp_path)
    reloaded = load_space("pulled_vendas", base_dir=tmp_path)
    recompiled = compile_space(reloaded)

    assert recompiled == original_compiled
    assert reloaded.space.environments["dev"].space_id == "01ef9999000011112222333344445555"
    assert len(reloaded.sources.tables) == 2
    assert len(reloaded.sources.metric_views) == 1
    assert len(reloaded.sources.volumes) == 1
    assert len(reloaded.instructions.join_specs) == 1
    assert len(reloaded.instructions.sql_functions) == 3
    assert len(reloaded.benchmarks.questions) == 32
