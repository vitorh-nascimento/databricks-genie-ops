"""Diagnosticador de falhas de benchmark seguindo a hierarquia oficial de correção Databricks Genie."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from genieops.history import BenchmarkItemResult, BenchmarkRunRecord
from genieops.models import SpaceBundle

# Hierarquia oficial de alavancas (da menor superfície estruturada até instrução global por último)
FIX_LEVER_HIERARCHY = [
    "1. Escopo e descrições de fontes (sources.yaml)",
    "2. Descrições de colunas, sinônimos e exclusão de ruído (column_configs)",
    "3. Entity Matching e Format Assistance seletivos (column_configs)",
    "4. Metadados / medidas governadas de Metric View",
    "5. Join Specs validados por chaves e grão (instructions.join_specs)",
    "6. SQL Snippets reutilizáveis: measures, filters, expressions",
    "7. Exemplo SQL representativo por formato de query (example_question_sqls)",
    "8. Instrução global curta em text_instructions (último recurso)",
]


@dataclass
class FailureDiagnosis:
    """Diagnóstico estruturado de uma falha individual."""

    case_id: str
    question: str
    root_cause_class: str
    confidence: str  # HIGH | MEDIUM | LOW
    evidence: list[str] = field(default_factory=list)
    recommended_lever: str = ""
    proposed_action: str = ""
    avoid_antipattern: str = ""


@dataclass
class DiagnosisReport:
    """Plano completo de diagnóstico para um run de benchmark (somente leitura; requer aprovação)."""

    space_name: str
    run_id: str
    total_failures: int
    diagnoses: list[FailureDiagnosis] = field(default_factory=list)


def _extract_tables_from_sql(sql: str | None) -> set[str]:
    if not sql:
        return set()
    matches = re.findall(r"\b(?:FROM|JOIN)\s+([`A-Za-z0-9_.-]+)", sql, flags=re.IGNORECASE)
    return {m.replace("`", "").split(".")[-1].lower() for m in matches}


def _extract_string_literals(sql: str | None) -> set[str]:
    if not sql:
        return set()
    return {m.lower() for m in re.findall(r"'([^']+)'", sql)}


def diagnose_item(item: BenchmarkItemResult, bundle: SpaceBundle) -> FailureDiagnosis:
    """Classifica a causa raiz e sugere a correção estruturada mínima para um item falho."""
    err = (item.error_message or "").lower()
    exp_sql = item.expected_sql or ""
    gen_sql = item.generated_sql or ""
    evidence: list[str] = list(item.details)

    # 1. Erro de infraestrutura / permissão / timeout / execução SQL
    if any(k in err for k in ("permission", "insufficient", "timeout", "table_or_view_not_found", "sql_execution_exception")):
        return FailureDiagnosis(
            case_id=item.case_id,
            question=item.question,
            root_cause_class="Infra / permission / execution error",
            confidence="HIGH",
            evidence=evidence or [item.error_message or "Erro de execução/permissão."],
            recommended_lever="Correção de infraestrutura/permissões no Unity Catalog ou SQL Warehouse",
            proposed_action="Verifique privilégios SELECT/USE CATALOG/USE SCHEMA e status do SQL Warehouse antes de alterar curadoria.",
            avoid_antipattern="Não adicionar text_instructions para tentar contornar erros de permissão ou tabela inexistente.",
        )

    # 2. Ground Truth inválido ou benchmark mal formado
    if not exp_sql.strip() and item.mode == "chat":
        return FailureDiagnosis(
            case_id=item.case_id,
            question=item.question,
            root_cause_class="Benchmark ground truth",
            confidence="HIGH",
            evidence=["Caso em modo chat sem ground_truth_sql."],
            recommended_lever="Reparo de benchmark (benchmarks.yaml)",
            proposed_action="Forneça um ground_truth_sql validado ou altere o caso para mode: agent com evaluation_note.",
            avoid_antipattern="Não ajustar o Genie Space para compensar benchmark quebrado.",
        )

    # 3. Metric View measure / grain
    mv_names = {mv.identifier.split(".")[-1].lower() for mv in bundle.sources.metric_views}
    exp_tables = _extract_tables_from_sql(exp_sql)
    gen_tables = _extract_tables_from_sql(gen_sql)
    if (exp_tables & mv_names) or "measure(" in exp_sql.lower() or "missing_aggregation" in err:
        if "measure(" not in gen_sql.lower() or "missing_aggregation" in err:
            return FailureDiagnosis(
                case_id=item.case_id,
                question=item.question,
                root_cause_class="Wrong Metric View measure",
                confidence="HIGH",
                evidence=evidence + ["Ground truth utiliza Metric View / MEASURE(), ausente ou inválido no SQL gerado."],
                recommended_lever="4. Metadados / medidas governadas de Metric View + exemplo MEASURE()",
                proposed_action="Enriqueça display_name/descrição da medida na Metric View e inclua 1 exemplo genérico de uso com MEASURE() sem WHERE sobre medida.",
                avoid_antipattern="Não reescrever a fórmula da medida governada em text_instructions ou sql_snippets duplicados.",
            )

    # 4. Wrong source / field
    if exp_tables and gen_tables and not (exp_tables & gen_tables):
        return FailureDiagnosis(
            case_id=item.case_id,
            question=item.question,
            root_cause_class="Wrong source / field",
            confidence="HIGH",
            evidence=evidence + [f"Esperado: {sorted(exp_tables)} | Gerado: {sorted(gen_tables)}"],
            recommended_lever="1. Escopo e descrições de fontes (sources.yaml) + 2. column_configs",
            proposed_action=(
                f"Diferencie claramente a descrição de negócio de {sorted(exp_tables)} vs {sorted(gen_tables)} "
                "e adicione sinônimos nas colunas-chave."
            ),
            avoid_antipattern="Evite criar regra em text_instructions dizendo 'Para a pergunta X use tabela Y'.",
        )

    # 5. Wrong join / grain
    exp_has_join = " join " in f" {exp_sql.lower()} "
    gen_has_join = " join " in f" {gen_sql.lower()} "
    if exp_has_join != gen_has_join or (exp_tables != gen_tables and len(exp_tables) > 1):
        return FailureDiagnosis(
            case_id=item.case_id,
            question=item.question,
            root_cause_class="Wrong join / grain",
            confidence="HIGH",
            evidence=evidence + [f"Junção divergente — tabelas esperadas={sorted(exp_tables)}, geradas={sorted(gen_tables)}"],
            recommended_lever="5. Join Specs validados por chaves e grão (instructions.join_specs)",
            proposed_action="Cadastre ou revise o join_spec em instructions.yaml com colunas qualificadas e tipo de relacionamento (ONE_TO_MANY / MANY_TO_ONE) validado nos dados.",
            avoid_antipattern="Não inferir join apenas por similaridade de nome sem validar PK/FK e cardinalidade.",
        )

    # 6. Wrong filter value (literais ou casing diferentes)
    exp_lits = _extract_string_literals(exp_sql)
    gen_lits = _extract_string_literals(gen_sql)
    if exp_lits and exp_lits != gen_lits:
        return FailureDiagnosis(
            case_id=item.case_id,
            question=item.question,
            root_cause_class="Wrong filter value",
            confidence="HIGH",
            evidence=evidence + [f"Literais esperados={sorted(exp_lits)} vs gerados={sorted(gen_lits)}"],
            recommended_lever="3. Entity Matching + Format Assistance + synonyms em column_configs (ou sql_snippets.filters)",
            proposed_action="Ative enable_entity_matching e enable_format_assistance na coluna categórica filtrada e cadastre synonyms mapeando os termos de negócio.",
            avoid_antipattern="Não fazer hardcode de mapeamento de valor em text_instructions nem copiar o filtro do benchmark em example_question_sqls.",
        )

    # 7. Instruction conflict / overload
    if len("\n".join(bundle.instructions.text_instructions)) > 2000:
        return FailureDiagnosis(
            case_id=item.case_id,
            question=item.question,
            root_cause_class="Instruction conflict / overload",
            confidence="MEDIUM",
            evidence=evidence + ["Bloco text_instructions extenso pode estar conflitando com metadados estruturados."],
            recommended_lever="2. column_configs / 6. sql_snippets (enxugar text_instructions)",
            proposed_action="Revise conflitos entre text_instructions, snippets e column_configs; mova regras específicas de coluna/filtro para superfícies estruturadas.",
            avoid_antipattern="Não adicionar mais parágrafos em text_instructions para tentar corrigir conflito anterior.",
        )

    # 8. Business / time logic (agregação, janela temporal, ranking, divisão)
    return FailureDiagnosis(
        case_id=item.case_id,
        question=item.question,
        root_cause_class="Business / time logic",
        confidence="MEDIUM",
        evidence=evidence or ["Lógica de agregação, janela temporal ou filtro de negócio divergente."],
        recommended_lever="6. SQL Snippets reutilizáveis -> 7. Exemplo SQL representativo (sem leakage)",
        proposed_action="Modele o cálculo ou janela temporal como sql_snippet (measure/filter/expression) com colunas qualificadas e, se o formato da query for complexo, inclua 1 exemplo genérico de padrão equivalente.",
        avoid_antipattern="Não copiar literalmente a pergunta/SQL do benchmark para example_question_sqls (causa leakage).",
    )


def diagnose_run(run: BenchmarkRunRecord, bundle: SpaceBundle) -> DiagnosisReport:
    """Gera plano estruturado de diagnóstico para todas as falhas (status == 'BAD') de uma rodada."""
    failures = [it for it in run.items if it.status == "BAD"]
    diagnoses = [diagnose_item(it, bundle) for it in failures]
    return DiagnosisReport(
        space_name=bundle.space.name,
        run_id=run.run_id,
        total_failures=len(failures),
        diagnoses=diagnoses,
    )
