"""Modelos Pydantic para a especificação declarativa Genie-as-Code e payload serialized_space v2."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

HEX_32_RE = re.compile(r"^[0-9a-f]{32}$")


def _ensure_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    return [str(value)]


class EnvironmentConfig(BaseModel):
    """Configuração de ambiente (dev, qa, prod) para um Genie Space."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str | None = None
    profile: str | None = None
    warehouse_id: str | None = None
    catalog: str | None = None
    schema_name: str | None = Field(default=None, alias="schema")
    volume_catalog: str | None = None
    volume_schema: str | None = None
    parent_path: str | None = None
    space_id: str | None = None
    workspace_url: str | None = None

    def merge_with(self, override: EnvironmentConfig | None) -> EnvironmentConfig:
        """Retorna novo EnvironmentConfig aplicando valores não nulos de `override`."""
        if override is None:
            return self.model_copy(deep=True)
        base_data = self.model_dump(by_alias=True)
        override_data = override.model_dump(by_alias=True, exclude_none=True)
        merged = {**base_data, **override_data}
        return EnvironmentConfig.model_validate(merged)


class SpaceConfig(BaseModel):
    """Metadados e ambientes definidos em space.yaml."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str
    title: str
    description: str = ""
    target_audience: str = ""
    owner: str = ""
    domains: list[str] = Field(default_factory=list)
    default_env: str = "dev"
    environments: dict[str, EnvironmentConfig] = Field(default_factory=dict)


class ColumnConfig(BaseModel):
    """Configuração semântica por coluna no Unity Catalog."""

    model_config = ConfigDict(extra="ignore")

    column_name: str
    description: list[str] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    enable_entity_matching: bool | None = None
    enable_format_assistance: bool | None = None
    exclude: bool | None = None

    @field_validator("description", mode="before")
    @classmethod
    def _norm_description(cls, v: Any) -> list[str]:
        return _ensure_str_list(v)

    @field_validator("synonyms", mode="before")
    @classmethod
    def _norm_synonyms(cls, v: Any) -> list[str]:
        return _ensure_str_list(v)


class TableSource(BaseModel):
    """Tabela ou Metric View do Unity Catalog."""

    model_config = ConfigDict(extra="ignore")

    identifier: str
    description: list[str] = Field(default_factory=list)
    column_configs: list[ColumnConfig] = Field(default_factory=list)

    @field_validator("description", mode="before")
    @classmethod
    def _norm_description(cls, v: Any) -> list[str]:
        return _ensure_str_list(v)


class VolumeSource(BaseModel):
    """UC Volume gerenciado contendo documentos para Agent Mode."""

    model_config = ConfigDict(extra="ignore")

    path: str
    description: list[str] = Field(default_factory=list)

    @field_validator("description", mode="before")
    @classmethod
    def _norm_description(cls, v: Any) -> list[str]:
        return _ensure_str_list(v)


class SourcesConfig(BaseModel):
    """Fontes de dados definidas em sources.yaml."""

    model_config = ConfigDict(extra="ignore")

    tables: list[TableSource] = Field(default_factory=list)
    metric_views: list[TableSource] = Field(default_factory=list)
    volumes: list[VolumeSource] = Field(default_factory=list)


class JoinEndpoint(BaseModel):
    """Lado esquerdo ou direito de um Join Spec."""

    identifier: str
    alias: str


RelationshipType = Literal["ONE_TO_MANY", "MANY_TO_ONE", "ONE_TO_ONE", "MANY_TO_MANY"]


class JoinSpec(BaseModel):
    """Especificação de relacionamento entre tabelas."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    left: JoinEndpoint
    right: JoinEndpoint
    condition: str
    relationship_type: RelationshipType = "ONE_TO_MANY"


class SqlSnippetMeasure(BaseModel):
    """Medida SQL reutilizável."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    alias: str
    display_name: str
    sql: str
    synonyms: list[str] = Field(default_factory=list)

    @field_validator("synonyms", mode="before")
    @classmethod
    def _norm_synonyms(cls, v: Any) -> list[str]:
        return _ensure_str_list(v)


class SqlSnippetFilter(BaseModel):
    """Filtro SQL reutilizável."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    display_name: str
    sql: str
    synonyms: list[str] = Field(default_factory=list)

    @field_validator("synonyms", mode="before")
    @classmethod
    def _norm_synonyms(cls, v: Any) -> list[str]:
        return _ensure_str_list(v)


class SqlSnippetExpression(BaseModel):
    """Expressão/dimensão derivada SQL reutilizável."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    alias: str
    display_name: str
    sql: str
    synonyms: list[str] = Field(default_factory=list)

    @field_validator("synonyms", mode="before")
    @classmethod
    def _norm_synonyms(cls, v: Any) -> list[str]:
        return _ensure_str_list(v)


class SqlSnippetsConfig(BaseModel):
    """Agrupamento de SQL snippets."""

    model_config = ConfigDict(extra="ignore")

    measures: list[SqlSnippetMeasure] = Field(default_factory=list)
    filters: list[SqlSnippetFilter] = Field(default_factory=list)
    expressions: list[SqlSnippetExpression] = Field(default_factory=list)


class SqlFunction(BaseModel):
    """Função SQL registrada no Unity Catalog (Trusted Asset) referenciada pelo Genie."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    identifier: str
    description: str | None = None


class ExampleQuestionSql(BaseModel):
    """Exemplo instrutivo pergunta -> SQL."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    question: str
    sql: str
    description: str | None = None


class SampleQuestion(BaseModel):
    """Pergunta sugerida exibida na UI do Genie."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    question: str


class InstructionsConfig(BaseModel):
    """Instruções e artefatos semânticos em instructions.yaml."""

    model_config = ConfigDict(extra="ignore")

    join_specs: list[JoinSpec] = Field(default_factory=list)
    sql_snippets: SqlSnippetsConfig = Field(default_factory=SqlSnippetsConfig)
    sql_functions: list[SqlFunction] = Field(default_factory=list)
    example_question_sqls: list[ExampleQuestionSql] = Field(default_factory=list)
    text_instructions: list[str] = Field(default_factory=list)
    text_instruction_id: str | None = None
    sample_questions: list[SampleQuestion] = Field(default_factory=list)

    @field_validator("text_instructions", mode="before")
    @classmethod
    def _norm_text_instructions(cls, v: Any) -> list[str]:
        return _ensure_str_list(v)

    @field_validator("sql_functions", mode="before")
    @classmethod
    def _norm_sql_functions(cls, v: Any) -> list[dict[str, Any]]:
        if not v:
            return []
        normalized: list[dict[str, Any]] = []
        for item in v:
            if isinstance(item, str):
                normalized.append({"identifier": item.strip()})
            elif isinstance(item, dict):
                normalized.append(item)
            elif isinstance(item, SqlFunction):
                normalized.append(item.model_dump())
        return normalized

    @field_validator("sample_questions", mode="before")
    @classmethod
    def _norm_sample_questions(cls, v: Any) -> list[dict[str, Any]]:
        if not v:
            return []
        normalized: list[dict[str, Any]] = []
        for item in v:
            if isinstance(item, str):
                normalized.append({"question": item})
            elif isinstance(item, dict):
                normalized.append(item)
            elif isinstance(item, SampleQuestion):
                normalized.append(item.model_dump())
        return normalized


DifficultyLevel = Literal["easy", "medium", "hard"]
EvalMode = Literal["chat", "agent"]


class BenchmarkCase(BaseModel):
    """Caso individual da suíte de benchmark em benchmarks.yaml."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    question: str
    paraphrases: list[str] = Field(default_factory=list)
    ground_truth_sql: str | None = None
    expected_tables: list[str] = Field(default_factory=list)
    required_clauses: list[str] = Field(default_factory=list)
    semantic_criteria: list[str] = Field(default_factory=list)
    domain: str = "Geral"
    difficulty: DifficultyLevel = "medium"
    tags: list[str] = Field(default_factory=list)
    mode: EvalMode = "chat"
    evaluation_note: str | None = None

    @field_validator(
        "paraphrases",
        "expected_tables",
        "required_clauses",
        "semantic_criteria",
        "tags",
        mode="before",
    )
    @classmethod
    def _norm_lists(cls, v: Any) -> list[str]:
        return _ensure_str_list(v)


class BenchmarksConfig(BaseModel):
    """Suíte de benchmarks em benchmarks.yaml."""

    model_config = ConfigDict(extra="ignore")

    questions: list[BenchmarkCase] = Field(default_factory=list)


class SpaceBundle(BaseModel):
    """Agregado completo de um Genie Space carregado do repositório."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    space: SpaceConfig
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    instructions: InstructionsConfig = Field(default_factory=InstructionsConfig)
    benchmarks: BenchmarksConfig = Field(default_factory=BenchmarksConfig)
    root_dir: Path | None = None
