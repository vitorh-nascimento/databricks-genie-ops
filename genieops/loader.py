"""Leitura, escrita, resolução de ambientes e scaffold de Genie Spaces (spaces/<nome>/)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from genieops.models import (
    BenchmarkCase,
    BenchmarksConfig,
    ColumnConfig,
    EnvironmentConfig,
    ExampleQuestionSql,
    InstructionsConfig,
    SampleQuestion,
    SourcesConfig,
    SpaceBundle,
    SpaceConfig,
    TableSource,
)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data if isinstance(data, dict) else {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(
            data,
            fh,
            sort_keys=False,
            allow_unicode=True,
            width=110,
            default_flow_style=False,
        )


def resolve_spaces_root(base_dir: Path | None = None) -> Path:
    root = base_dir or Path.cwd()
    return root / "spaces"


def resolve_env_config(
    bundle: SpaceBundle,
    env_name: str | None = None,
    base_dir: Path | None = None,
) -> EnvironmentConfig:
    """Resolve configuração efetiva de ambiente combinando env/<env>.yaml + space.yaml."""
    target_env = env_name or bundle.space.default_env or "dev"
    root = base_dir or (bundle.root_dir.parent.parent if bundle.root_dir else Path.cwd())
    global_env_path = root / "env" / f"{target_env}.yaml"
    global_cfg = (
        EnvironmentConfig.model_validate(_read_yaml(global_env_path))
        if global_env_path.exists()
        else EnvironmentConfig(name=target_env)
    )
    space_env_cfg = bundle.space.environments.get(target_env)
    merged = global_cfg.merge_with(space_env_cfg)
    if not merged.name:
        merged.name = target_env
    return merged


def list_spaces(base_dir: Path | None = None) -> list[str]:
    """Lista nomes dos Genie Spaces registrados em spaces/."""
    spaces_dir = resolve_spaces_root(base_dir)
    if not spaces_dir.exists():
        return []
    return sorted(
        d.name for d in spaces_dir.iterdir() if d.is_dir() and (d / "space.yaml").exists()
    )


def load_space(name: str, base_dir: Path | None = None) -> SpaceBundle:
    """Carrega todos os arquivos YAML de um Genie Space."""
    space_dir = resolve_spaces_root(base_dir) / name
    if not space_dir.exists():
        raise FileNotFoundError(f"Genie Space '{name}' não encontrado em {space_dir}")

    space_data = _read_yaml(space_dir / "space.yaml")
    if "name" not in space_data:
        space_data["name"] = name

    sources_data = _read_yaml(space_dir / "sources.yaml")
    instructions_data = _read_yaml(space_dir / "instructions.yaml")
    benchmarks_data = _read_yaml(space_dir / "benchmarks.yaml")

    return SpaceBundle(
        space=SpaceConfig.model_validate(space_data),
        sources=SourcesConfig.model_validate(sources_data),
        instructions=InstructionsConfig.model_validate(instructions_data),
        benchmarks=BenchmarksConfig.model_validate(benchmarks_data),
        root_dir=space_dir,
    )


def save_space(bundle: SpaceBundle, base_dir: Path | None = None) -> Path:
    """Persiste um SpaceBundle em spaces/<name>/*.yaml de forma limpa e determinística."""
    space_dir = bundle.root_dir or (resolve_spaces_root(base_dir) / bundle.space.name)
    space_dir.mkdir(parents=True, exist_ok=True)

    space_dump = bundle.space.model_dump(by_alias=True, exclude_none=True)
    sources_dump = bundle.sources.model_dump(exclude_none=True)

    inst_dump = bundle.instructions.model_dump(exclude_none=True)
    # Compacta sample_questions simples sem id para melhorar legibilidade se não houver id
    if "sample_questions" in inst_dump:
        inst_dump["sample_questions"] = [
            sq["question"] if not sq.get("id") else sq for sq in inst_dump["sample_questions"]
        ]

    benchmarks_dump = bundle.benchmarks.model_dump(exclude_none=True)

    _write_yaml(space_dir / "space.yaml", space_dump)
    _write_yaml(space_dir / "sources.yaml", sources_dump)
    _write_yaml(space_dir / "instructions.yaml", inst_dump)
    _write_yaml(space_dir / "benchmarks.yaml", benchmarks_dump)

    bundle.root_dir = space_dir
    return space_dir


def init_space_scaffold(
    name: str,
    title: str | None = None,
    catalog: str = "analytics_dev",
    schema: str = "domain_gold",
    base_dir: Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Cria o scaffold declarativo inicial de um novo Genie Space."""
    space_dir = resolve_spaces_root(base_dir) / name
    if space_dir.exists() and not overwrite:
        raise FileExistsError(f"O diretório do space '{name}' já existe em {space_dir}")

    human_title = title or name.replace("_", " ").replace("-", " ").title()
    table_id = f"{catalog}.{schema}.fct_exemplo"

    bundle = SpaceBundle(
        space=SpaceConfig(
            name=name,
            title=human_title,
            description=(
                f"Genie Space curado para o domínio {human_title}, "
                "habilitando consultas analíticas em linguagem natural com governança no Unity Catalog."
            ),
            target_audience="Analistas de negócio, gestores e liderança executiva",
            owner="Data & Analytics Team",
            domains=[human_title],
            default_env="dev",
            environments={
                "dev": EnvironmentConfig(
                    profile="dev-workspace",
                    warehouse_id="<DEV_SQL_WAREHOUSE_ID>",
                    catalog=catalog,
                    schema=schema,
                    parent_path=f"/Workspace/Shared/genie_spaces/dev/{name}",
                ),
                "prod": EnvironmentConfig(
                    profile="prod-workspace",
                    warehouse_id="<PROD_SQL_WAREHOUSE_ID>",
                    catalog=catalog.replace("_dev", "_prod") if "_dev" in catalog else f"{catalog}_prod",
                    schema=schema,
                    parent_path=f"/Workspace/Shared/genie_spaces/prod/{name}",
                ),
            },
        ),
        sources=SourcesConfig(
            tables=[
                TableSource(
                    identifier=table_id,
                    description=["Tabela fato principal do domínio com granularidade diária."],
                    column_configs=[
                        ColumnConfig(column_name="id_registro", exclude=True),
                        ColumnConfig(
                            column_name="data_referencia",
                            description=["Data de competência do evento (YYYY-MM-DD)."],
                        ),
                        ColumnConfig(
                            column_name="categoria",
                            description=["Categoria principal de negócio."],
                            synonyms=["grupo", "segmento"],
                            enable_entity_matching=True,
                            enable_format_assistance=True,
                        ),
                        ColumnConfig(
                            column_name="valor_total",
                            description=["Valor monetário consolidado em moeda local."],
                        ),
                    ],
                )
            ]
        ),
        instructions=InstructionsConfig(
            example_question_sqls=[
                ExampleQuestionSql(
                    question="Qual foi o valor total acumulado por categoria no último mês?",
                    sql=(
                        f"SELECT categoria, SUM(valor_total) AS total "
                        f"FROM {table_id} "
                        f"WHERE data_referencia >= date_trunc('month', add_months(current_date(), -1)) "
                        f"GROUP BY categoria ORDER BY total DESC"
                    ),
                )
            ],
            text_instructions=[
                "Responda sempre em português claro, destacando período analisado e unidade monetária.",
                "Quando o usuário não especificar período, considere o mês corrente de data_referencia.",
            ],
            sample_questions=[
                SampleQuestion(question="Qual foi o valor total por categoria neste mês?"),
                SampleQuestion(question="Qual a evolução mensal do valor total nos últimos 6 meses?"),
            ],
        ),
        benchmarks=BenchmarksConfig(
            questions=[
                BenchmarkCase(
                    id="bmk_01",
                    question="Qual o valor total registrado por categoria em 2026?",
                    ground_truth_sql=(
                        f"SELECT categoria, SUM(valor_total) AS total "
                        f"FROM {table_id} WHERE YEAR(data_referencia) = 2026 "
                        f"GROUP BY categoria ORDER BY total DESC"
                    ),
                    expected_tables=["fct_exemplo"],
                    required_clauses=["SUM(valor_total)", "GROUP BY categoria"],
                    domain=human_title,
                    difficulty="easy",
                    tags=["agregacao", "categoria"],
                )
            ]
        ),
        root_dir=space_dir,
    )
    return save_space(bundle, base_dir=base_dir)
