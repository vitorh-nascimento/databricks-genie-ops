"""Linter e auditoria automatizada ('Genie Health Check') para espaços Genie-as-Code."""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from typing import Literal

from genieops.compiler import compile_space
from genieops.databricks_client import DatabricksClient
from genieops.models import HEX_32_RE, SpaceBundle

Severity = Literal["ERROR", "WARNING", "INFO"]

# Padrões heurísticos para detecção de colunas técnicas/medidas vs categóricas
NON_CATEGORICAL_COL_RE = re.compile(
    r"(^id_|_id$|^pk_|^sk_|hash|uuid|guid|cpf|cnpj|valor|amount|total_|qtd|qty|price|preco|custo|receita|lucro|taxa|pct|lat$|lon$|longitude|latitude|_ts$|_at$|_em$)",
    re.IGNORECASE,
)
LIKELY_CATEGORICAL_COL_RE = re.compile(
    r"(^status|_status$|^tipo|_tipo$|^categoria|_categoria$|^regiao$|^region$|^segmento$|^segment$|^canal|^channel|^uf$|^estado$|^pais$|^country$|^forma_pagamento|^porte_)",
    re.IGNORECASE,
)
SQL_KEYWORDS_AND_FUNCS = {
    "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "IN", "IS", "NULL", "TRUE", "FALSE",
    "CASE", "WHEN", "THEN", "ELSE", "END", "AS", "ON", "BY", "GROUP", "ORDER", "ASC", "DESC",
    "LIMIT", "HAVING", "DISTINCT", "BETWEEN", "LIKE", "ILIKE", "RLIKE", "CAST", "TRY_CAST",
    "SUM", "AVG", "COUNT", "MIN", "MAX", "ROUND", "COALESCE", "NULLIF", "ABS", "FLOOR", "CEIL",
    "YEAR", "MONTH", "DAY", "DATE", "CURRENT_DATE", "CURRENT_TIMESTAMP", "DATE_TRUNC", "DATE_SUB",
    "DATE_ADD", "ADD_MONTHS", "LAST_DAY", "DATEDIFF", "INTERVAL", "DAYS", "MONTHS", "YEARS",
    "UPPER", "LOWER", "TRIM", "SUBSTRING", "CONCAT", "LENGTH", "MEASURE", "INT", "BIGINT",
    "DOUBLE", "DECIMAL", "STRING", "BOOLEAN", "FLOAT", "TIMESTAMP", "OVER", "PARTITION",
    "ROW_NUMBER", "RANK", "DENSE_RANK", "EXTRACT", "EXISTS",
}

TEXT_INSTRUCTION_SMELL_RE = re.compile(
    r"(\bWHERE\s+[A-Za-z0-9_.]+\s*=|\bILIKE\s+'|\bLIKE\s+'|\bIN\s*\(\s*')|(\b[a-z_]+\s*=\s*'[^']+')",
    re.IGNORECASE,
)


@dataclass
class LintIssue:
    code: str
    severity: Severity
    surface: str
    message: str
    recommendation: str = ""


@dataclass
class LintReport:
    space_name: str
    issues: list[LintIssue] = field(default_factory=list)
    sql_validated_count: int = 0
    sql_failed_count: int = 0

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "ERROR")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "WARNING")

    @property
    def info_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "INFO")

    @property
    def passed(self) -> bool:
        return self.error_count == 0

    @property
    def health_score(self) -> int:
        score = 100 - (self.error_count * 20) - (self.warning_count * 5) - (self.info_count * 1)
        return max(0, min(100, score))


def _normalize_sql_for_comparison(sql: str) -> str:
    s = re.sub(r"--[^\n]*", " ", sql)
    s = re.sub(r"\s+", " ", s).strip().rstrip(";").lower()
    return s


def _normalize_text(text: str) -> str:
    s = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", s).strip()


def find_unqualified_columns(sql_expr: str) -> list[str]:
    """
    Detecta colunas potencialmente não qualificadas (sem `tabela.` ou `alias.`) em
    `sql_snippets` e `join_specs`, prevenindo `Table name or alias is required for column`.
    """
    if not sql_expr or not sql_expr.strip():
        return []

    # Remove strings literais ('...'), placeholders (<...>) e parâmetros (:param)
    cleaned = re.sub(r"'[^']*'", " ", sql_expr)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r":[A-Za-z_][A-Za-z0-9_]*", " ", cleaned)

    unqualified: list[str] = []

    # 1. Colunas entre crases sem prefixo de tabela: `col` sem ponto imediatamente antes
    for match in re.finditer(r"(?<!\.)`([A-Za-z_][A-Za-z0-9_]*)`(?!\s*\.)", cleaned):
        ident = match.group(1)
        if ident.upper() not in SQL_KEYWORDS_AND_FUNCS:
            unqualified.append(ident)

    # Remove expressões já qualificadas (ex: `tbl`.`col` ou tbl.col ou cat.sch.tbl.col)
    stripped = re.sub(
        r"(?:`?[A-Za-z_][A-Za-z0-9_]*`?\.)+`?[A-Za-z_][A-Za-z0-9_]*`?",
        " ",
        cleaned,
    )
    # Remove chamadas de função (identificador seguido imediatamente de '(')
    stripped = re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\s*(?=\()", " ", stripped)
    # Remove nomes de crase já checados
    stripped = re.sub(r"`[^`]+`", " ", stripped)

    # 2. Identificadores nus remanescentes
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", stripped):
        tok = match.group(1)
        if tok.upper() in SQL_KEYWORDS_AND_FUNCS:
            continue
        if tok.isdigit():
            continue
        if tok not in unqualified:
            unqualified.append(tok)

    return unqualified


def lint_space(
    bundle: SpaceBundle,
    validate_sql: bool = False,
    client: DatabricksClient | None = None,
    warehouse_id: str | None = None,
) -> LintReport:
    """Executa auditoria estática completa e, opcionalmente, validação EXPLAIN no SQL Warehouse."""
    report = LintReport(space_name=bundle.space.name)

    def add(code: str, severity: Severity, surface: str, message: str, rec: str = "") -> None:
        report.issues.append(
            LintIssue(code=code, severity=severity, surface=surface, message=message, recommendation=rec)
        )

    # 1. Metadados do Space
    if not bundle.space.description or len(bundle.space.description.strip()) < 20:
        add(
            "SRC003",
            "WARNING",
            "space.yaml",
            "Descrição do Genie Space ausente ou muito curta.",
            "Defina uma descrição clara indicando escopo, domínio e público-alvo.",
        )

    # 2. Contagem de fontes (tables + metric_views + volumes)
    total_tabular = len(bundle.sources.tables) + len(bundle.sources.metric_views)
    total_volumes = len(bundle.sources.volumes)
    if total_tabular == 0 and total_volumes == 0:
        add(
            "SRC001",
            "ERROR",
            "sources.yaml",
            "Nenhuma fonte de dados (table, metric_view ou volume) cadastrada.",
            "Adicione ao menos uma tabela, Metric View ou UC Volume em sources.yaml.",
        )
    elif total_tabular > 30:
        add(
            "SRC001",
            "ERROR",
            "sources.yaml",
            f"Total de fontes tabulares ({total_tabular}) excede o limite máximo da API Databricks (30).",
            "Divida o domínio em múltiplos Genie Spaces especializados.",
        )
    elif total_tabular > 5:
        add(
            "SRC001",
            "WARNING",
            "sources.yaml",
            f"Total de fontes tabulares ({total_tabular}) acima do recomendado (<= 5).",
            "Mantenha o espaço focado em <= 5 tabelas/Metric Views para evitar confusão de roteamento.",
        )

    if total_volumes > 10:
        add(
            "SRC002",
            "ERROR",
            "sources.yaml",
            f"Total de volumes ({total_volumes}) excede o limite de 10 volumes por Agent.",
            "Reduza para no máximo 10 UC Volumes gerenciados.",
        )
    for vol in bundle.sources.volumes:
        if not vol.path.startswith("/Volumes/"):
            add(
                "SRC002",
                "ERROR",
                f"sources.volumes[{vol.path}]",
                f"Caminho de volume inválido: '{vol.path}'. Deve iniciar com '/Volumes/'.",
                "Use o formato '/Volumes/<catalog>/<schema>/<volume>'.",
            )
        if not vol.description:
            add(
                "SRC002",
                "WARNING",
                f"sources.volumes[{vol.path}]",
                f"Volume '{vol.path}' sem descrição.",
                "Descreva quais documentos o volume contém e quando usá-lo vs tabelas.",
            )

    # 3. Qualidade de column_configs
    all_tabular = [("tables", t) for t in bundle.sources.tables] + [
        ("metric_views", mv) for mv in bundle.sources.metric_views
    ]
    for kind, src in all_tabular:
        if not src.description:
            add(
                "SRC004",
                "WARNING",
                f"sources.{kind}[{src.identifier}]",
                f"Fonte '{src.identifier}' sem descrição de negócio.",
                "Adicione uma descrição explicando grão, finalidade e diferenças para outras fontes.",
            )
        if not src.column_configs:
            add(
                "COL001",
                "WARNING",
                f"sources.{kind}[{src.identifier}]",
                f"Fonte '{src.identifier}' está com column_configs vazio.",
                "Popule column_configs com descrições, sinônimos, entity matching seletivo e exclusões.",
            )
            continue

        for col in src.column_configs:
            if col.exclude:
                continue
            if not col.description:
                add(
                    "COL002",
                    "WARNING",
                    f"{src.identifier}.{col.column_name}",
                    f"Coluna '{col.column_name}' sem descrição semântica.",
                    "Adicione description em column_configs ou marque exclude: true se for técnica.",
                )
            if col.enable_entity_matching and NON_CATEGORICAL_COL_RE.search(col.column_name):
                add(
                    "COL003",
                    "WARNING",
                    f"{src.identifier}.{col.column_name}",
                    f"enable_entity_matching ativado em coluna suspeita de ID/medida/timestamp ('{col.column_name}').",
                    "Use entity_matching apenas em dimensões categóricas de baixa/média cardinalidade.",
                )
            if not col.enable_entity_matching and LIKELY_CATEGORICAL_COL_RE.search(col.column_name):
                add(
                    "COL004",
                    "INFO",
                    f"{src.identifier}.{col.column_name}",
                    f"Coluna aparentemente categórica ('{col.column_name}') sem enable_entity_matching.",
                    "Avalie habilitar enable_entity_matching e enable_format_assistance após profiling.",
                )

    # 4. Qualificação de colunas em join_specs e sql_snippets
    for idx, js in enumerate(bundle.instructions.join_specs):
        if not js.condition or not js.condition.strip():
            add(
                "SQL001",
                "ERROR",
                f"instructions.join_specs[{idx}]",
                "Join spec com condição SQL vazia.",
                "Informe a expressão de junção qualificada com aliases.",
            )
        else:
            unq = find_unqualified_columns(js.condition)
            if unq:
                add(
                    "SQL001",
                    "ERROR",
                    f"instructions.join_specs[{idx}]",
                    f"Coluna(s) sem qualificação de tabela/alias em join_spec: {', '.join(unq)}.",
                    "Qualifique todas as colunas com alias da tabela (ex.: pedidos.id_cliente = clientes.id_cliente).",
                )

    for grp_name, items in (
        ("measures", bundle.instructions.sql_snippets.measures),
        ("filters", bundle.instructions.sql_snippets.filters),
        ("expressions", bundle.instructions.sql_snippets.expressions),
    ):
        for item in items:
            if not item.sql or not item.sql.strip():
                add(
                    "SQL001",
                    "ERROR",
                    f"instructions.sql_snippets.{grp_name}[{item.display_name}]",
                    f"SQL snippet '{item.display_name}' com expressão SQL vazia.",
                    "A API Databricks rejeita snippets vazios; informe uma expressão SQL qualificada.",
                )
                continue
            unq = find_unqualified_columns(item.sql)
            if unq:
                add(
                    "SQL001",
                    "ERROR",
                    f"instructions.sql_snippets.{grp_name}[{item.display_name}]",
                    f"Coluna(s) não qualificada(s) em sql_snippet '{item.display_name}': {', '.join(unq)}.",
                    "Prefixe toda coluna com o nome/alias da tabela para evitar 'Table name or alias is required for column'.",
                )

    # 4b. Validação de SQL Functions (Trusted Assets no Unity Catalog)
    seen_sql_fns: set[str] = set()
    for fn in bundle.instructions.sql_functions:
        ident = fn.identifier.strip()
        parts = [p for p in ident.split(".") if p.strip()]
        if len(parts) != 3:
            add(
                "SQLF001",
                "ERROR",
                f"instructions.sql_functions[{ident}]",
                f"Identificador de SQL Function inválido: '{ident}'. Use o formato completo 'catalog.schema.funcao'.",
                "Registre a função no Unity Catalog e informe o nome totalmente qualificado de 3 partes.",
            )
        norm_fn = ident.lower()
        if norm_fn in seen_sql_fns:
            add(
                "SQLF001",
                "WARNING",
                f"instructions.sql_functions[{ident}]",
                f"SQL Function duplicada em instructions.sql_functions: '{ident}'.",
                "Remova entradas duplicadas de Trusted Assets.",
            )
        seen_sql_fns.add(norm_fn)

    # 5. Regras de Metric View em example_question_sqls
    mv_short_names = [mv.identifier.split(".")[-1].lower() for mv in bundle.sources.metric_views]
    for ex in bundle.instructions.example_question_sqls:
        sql_low = ex.sql.lower()
        if any(mv_name in sql_low for mv_name in mv_short_names):
            if "measure(" not in sql_low:
                add(
                    "SQL002",
                    "WARNING",
                    f"instructions.example_question_sqls[{ex.question[:40]}]",
                    "Exemplo SQL referencia uma Metric View sem utilizar MEASURE().",
                    "Consultas em Metric Views devem agregar medidas governadas via MEASURE(<medida>).",
                )
            if re.search(r"\bwhere\b[^;]*\bmeasure\s*\(", sql_low):
                add(
                    "SQL002",
                    "ERROR",
                    f"instructions.example_question_sqls[{ex.question[:40]}]",
                    "Uso inválido de MEASURE() na cláusula WHERE.",
                    "Medidas de Metric View só podem ser filtradas via HAVING ou CTE/subquery externa.",
                )

    # 6. Detecção de Benchmark Leakage (example_question_sqls copiando benchmarks.yaml ou suas paráfrases)
    bmk_norm_questions: list[tuple[str, str]] = []
    for b in bundle.benchmarks.questions:
        ref = b.id or b.question[:30]
        bmk_norm_questions.append((ref, _normalize_text(b.question)))
        for p_idx, para in enumerate(b.paraphrases, start=1):
            bmk_norm_questions.append((f"{ref}#p{p_idx}", _normalize_text(para)))
    bmk_norm_sqls = [
        (b.id or b.question[:30], _normalize_sql_for_comparison(b.ground_truth_sql))
        for b in bundle.benchmarks.questions
        if b.ground_truth_sql
    ]

    for ex in bundle.instructions.example_question_sqls:
        ex_q_norm = _normalize_text(ex.question)
        ex_sql_norm = _normalize_sql_for_comparison(ex.sql)

        for b_ref, b_sql in bmk_norm_sqls:
            if ex_sql_norm == b_sql:
                add(
                    "LEAK001",
                    "ERROR",
                    f"instructions.example_question_sqls[{ex.question[:40]}]",
                    f"Benchmark Leakage detectado: SQL idêntico ao benchmark '{b_ref}'.",
                    "Mantenha exemplos genéricos por padrão de query; nunca copie o SQL exato do benchmark.",
                )
                break
            ratio = difflib.SequenceMatcher(None, ex_sql_norm, b_sql).ratio()
            if ratio >= 0.92:
                add(
                    "LEAK001",
                    "WARNING",
                    f"instructions.example_question_sqls[{ex.question[:40]}]",
                    f"Possível Benchmark Leakage: SQL {ratio * 100:.0f}% similar ao benchmark '{b_ref}'.",
                    "Reescreva o exemplo usando outro recorte/período para testar generalização real.",
                )
                break

        for b_ref, b_q in bmk_norm_questions:
            if ex_q_norm == b_q:
                add(
                    "LEAK001",
                    "ERROR",
                    f"instructions.example_question_sqls[{ex.question[:40]}]",
                    f"Benchmark Leakage detectado: pergunta idêntica ao benchmark '{b_ref}'.",
                    "Evite duplicar perguntas de avaliação em example_question_sqls.",
                )
                break

    # 7. Higiene de text_instructions
    ti_lines = bundle.instructions.text_instructions
    ti_joined = "\n".join(ti_lines)
    if len(ti_joined) > 2500 or len(ti_lines) > 15:
        add(
            "TXT001",
            "WARNING",
            "instructions.text_instructions",
            f"Bloco text_instructions inchado ({len(ti_lines)} linhas, {len(ti_joined)} chars).",
            "Mova definições de colunas, sinônimos e filtros para column_configs e sql_snippets; mantenha apenas regras globais.",
        )
    for line in ti_lines:
        if TEXT_INSTRUCTION_SMELL_RE.search(line):
            add(
                "TXT001",
                "WARNING",
                "instructions.text_instructions",
                f"text_instructions contém filtro/mapeamento literal de valor: '{line[:80]}...'",
                "Prefira enable_entity_matching, synonyms em column_configs ou sql_snippets.filters.",
            )
            break

    # 8. Qualidade da suíte de benchmarks
    bmk_list = bundle.benchmarks.questions
    valid_bmk = 0
    seen_bmk_questions: set[str] = set()
    domains: set[str] = set()
    difficulties: set[str] = set()

    for idx, bmk in enumerate(bmk_list):
        q_norm = _normalize_text(bmk.question)
        if q_norm in seen_bmk_questions:
            add(
                "BMK001",
                "WARNING",
                f"benchmarks.questions[{bmk.id or idx}]",
                f"Pergunta duplicada na suíte de benchmark: '{bmk.question[:60]}'.",
                "Remova duplicatas triviais para não distorcer a taxa de assertividade.",
            )
        seen_bmk_questions.add(q_norm)
        for p_idx, para in enumerate(bmk.paraphrases, start=1):
            p_norm = _normalize_text(para)
            if p_norm in seen_bmk_questions:
                add(
                    "BMK001",
                    "WARNING",
                    f"benchmarks.questions[{bmk.id or idx}].paraphrases[{p_idx}]",
                    f"Paráfrase duplicada na suíte de benchmark: '{para[:60]}'.",
                    "Use formulações realmente distintas para testar robustez linguística.",
                )
            seen_bmk_questions.add(p_norm)

        if bmk.mode == "chat" and not (bmk.ground_truth_sql and bmk.ground_truth_sql.strip()):
            add(
                "BMK001",
                "ERROR",
                f"benchmarks.questions[{bmk.id or idx}]",
                f"Benchmark em modo 'chat' sem ground_truth_sql: '{bmk.question[:50]}'.",
                "Forneça ground_truth_sql válido ou altere mode para 'agent' com evaluation_note.",
            )
        elif bmk.mode == "agent" and not (bmk.evaluation_note and bmk.evaluation_note.strip()):
            add(
                "BMK001",
                "WARNING",
                f"benchmarks.questions[{bmk.id or idx}]",
                f"Benchmark em modo 'agent' sem evaluation_note: '{bmk.question[:50]}'.",
                "Preencha evaluation_note com os critérios objetivos de avaliação da resposta.",
            )
        else:
            valid_bmk += 1

        domains.add(bmk.domain)
        difficulties.add(bmk.difficulty)

    if valid_bmk < 20:
        add(
            "BMK001",
            "WARNING",
            "benchmarks.yaml",
            f"Suíte de benchmark com apenas {valid_bmk} itens válidos (mínimo recomendado: >= 20; ideal: >= 30).",
            "Amplie a suíte cobrindo agregações, filtros, joins, janelas temporais e casos de borda.",
        )
    elif valid_bmk < 30:
        add(
            "BMK001",
            "INFO",
            "benchmarks.yaml",
            f"Suíte de benchmark com {valid_bmk} itens válidos (recomendação oficial Databricks para produção: >= 30).",
            "Considere adicionar mais cenários médios/difíceis a partir de perguntas reais de negócio.",
        )

    if valid_bmk >= 5 and len(difficulties) < 2:
        add(
            "BMK002",
            "INFO",
            "benchmarks.yaml",
            "Todos os benchmarks possuem a mesma dificuldade.",
            "Balanceie a suíte entre perguntas easy, medium e hard.",
        )

    # 9. Limites oficiais do payload compilado (IDs 32-hex, tamanho de string e JSON <= 3.5 MB)
    compiled = compile_space(bundle)
    serialized = json.dumps(compiled, separators=(",", ":"), ensure_ascii=False)
    size_bytes = len(serialized.encode("utf-8"))
    if size_bytes > 3_500_000:
        add(
            "LIM001",
            "ERROR",
            "serialized_space",
            f"Tamanho do payload compilado ({size_bytes / 1_000_000:.2f} MB) excede o limite de 3.5 MB.",
            "Reduza descrições excessivas ou divida em múltiplos spaces.",
        )

    for ti in compiled.get("instructions", {}).get("text_instructions", []):
        for s in ti.get("content", []):
            if len(s) > 25_000:
                add(
                    "LIM001",
                    "ERROR",
                    "instructions.text_instructions",
                    "String individual em text_instructions excede o limite de 25.000 caracteres.",
                    "Resuma as instruções globais.",
                )

    # Verifica unicidade e formato de todos os IDs compilados
    q_ids = [x["id"] for x in compiled.get("config", {}).get("sample_questions", [])] + [
        x["id"] for x in compiled.get("benchmarks", {}).get("questions", [])
    ]
    if len(q_ids) != len(set(q_ids)) or any(not HEX_32_RE.match(i) for i in q_ids):
        add("LIM001", "ERROR", "serialized_space", "IDs de perguntas inválidos ou duplicados.", "")

    inst_compiled = compiled.get("instructions", {})
    inst_ids = (
        [x["id"] for x in inst_compiled.get("text_instructions", [])]
        + [x["id"] for x in inst_compiled.get("example_question_sqls", [])]
        + [x["id"] for x in inst_compiled.get("join_specs", [])]
        + [x["id"] for x in inst_compiled.get("sql_functions", [])]
        + [x["id"] for x in inst_compiled.get("sql_snippets", {}).get("measures", [])]
        + [x["id"] for x in inst_compiled.get("sql_snippets", {}).get("filters", [])]
        + [x["id"] for x in inst_compiled.get("sql_snippets", {}).get("expressions", [])]
    )
    if len(inst_ids) != len(set(inst_ids)) or any(not HEX_32_RE.match(i) for i in inst_ids):
        add("LIM001", "ERROR", "serialized_space", "IDs de instruções inválidos ou duplicados.", "")

    # 10. Validação SQL real opcional (EXPLAIN read-only no SQL Warehouse)
    if validate_sql:
        if client is None:
            add(
                "SQLVAL",
                "ERROR",
                "validate-sql",
                "Cliente Databricks não fornecido para --validate-sql.",
                "Informe --env ou --profile configurado para executar EXPLAIN.",
            )
        else:
            sql_targets: list[tuple[str, str]] = []
            for ex in bundle.instructions.example_question_sqls:
                sql_targets.append((f"example_sql[{ex.question[:35]}]", ex.sql))
            for bmk in bundle.benchmarks.questions:
                if bmk.ground_truth_sql:
                    sql_targets.append((f"benchmark[{bmk.id or bmk.question[:35]}]", bmk.ground_truth_sql))

            for label, sql_text in sql_targets:
                report.sql_validated_count += 1
                ok, err = client.explain_sql(sql_text, warehouse_id=warehouse_id)
                if not ok:
                    report.sql_failed_count += 1
                    add(
                        "SQLVAL",
                        "ERROR",
                        label,
                        f"Falha no EXPLAIN SQL: {err}",
                        "Corrija sintaxe, nomes de tabela/coluna ou permissões antes do deploy.",
                    )

    return report
