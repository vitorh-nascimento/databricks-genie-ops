"""Kit de Curadoria GenieOps: gerador de base fictícia Star Schema (com armadilhas), COMMENTs UC e SQL Functions."""

from __future__ import annotations

from pathlib import Path

from genieops.models import SpaceBundle
from genieops.uc_export import quote_ident, sql_str, validate_uc_identifier


def _quote_three_part(identifier: str) -> str:
    parts = [p.strip() for p in identifier.strip().split(".")]
    if len(parts) != 3:
        raise ValueError(
            f"Identificador Unity Catalog inválido: '{identifier}'. Esperado 'catalog.schema.objeto'."
        )
    return ".".join(quote_ident(p) for p in parts)


def _quote_column(col_name: str) -> str:
    clean = validate_uc_identifier(col_name, "coluna")
    return f"`{clean}`"


def generate_uc_comments_sql(bundle: SpaceBundle, *, include_metric_views: bool = True) -> str:
    """
    Gera script Databricks SQL idempotente contendo `COMMENT ON TABLE` e
    `ALTER TABLE ... ALTER COLUMN ... COMMENT` a partir de `sources.yaml`.
    """
    lines: list[str] = [
        f"-- Databricks GenieOps — COMMENTs semânticos no Unity Catalog ({bundle.space.name})",
        f"-- Space: {bundle.space.title}",
        "-- Script revisável e idempotente para aplicar governança semântica diretamente no catálogo UC.",
        "",
    ]

    targets = list(bundle.sources.tables)
    if include_metric_views:
        targets.extend(bundle.sources.metric_views)

    if not targets:
        lines.append("-- Nenhuma tabela ou Metric View declarada em sources.yaml.")
        return "\n".join(lines) + "\n"

    for src in targets:
        fqn = _quote_three_part(src.identifier)
        lines.append(f"-- Fonte: {src.identifier}")
        if src.description:
            tbl_desc = " ".join(d.strip() for d in src.description if d.strip())
            lines.append(f"COMMENT ON TABLE {fqn} IS {sql_str(tbl_desc)};")

        for col in src.column_configs:
            if col.exclude:
                col_comment = (
                    "Coluna técnica/interna (excluída do contexto analítico do Genie)."
                    if not col.description
                    else " ".join(col.description)
                )
            else:
                parts: list[str] = []
                if col.description:
                    parts.append(" ".join(d.strip() for d in col.description if d.strip()))
                if col.synonyms:
                    parts.append(f"Sinônimos de negócio: {', '.join(col.synonyms)}.")
                if not parts:
                    continue
                col_comment = " ".join(parts)

            col_q = _quote_column(col.column_name)
            lines.append(
                f"ALTER TABLE {fqn} ALTER COLUMN {col_q} COMMENT {sql_str(col_comment)};"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_star_schema_seed_script(
    catalog: str,
    schema: str,
    *,
    rows_pedidos: int = 5000,
    rows_clientes: int = 300,
) -> str:
    """
    Gera script PySpark (compatível com Databricks Serverless / Notebooks) que cria
    uma base fictícia em esquema estrela com armadilhas reais de negócio para estudo de curadoria Genie.
    """
    cat_q = quote_ident(validate_uc_identifier(catalog, "catalog"))
    sch_q = quote_ident(validate_uc_identifier(schema, "schema"))
    prefix = f"{cat_q}.{sch_q}"

    return f'''# Databricks notebook source
"""
Databricks GenieOps — Gerador de Base Fictícia em Esquema Estrela (com Armadilhas de Negócio)
=============================================================================================
Cria tabelas Delta no Unity Catalog ({prefix}) prontas para curadoria progressiva de Genie Space:
  - {prefix}.dim_clientes   (Dimensão de clientes B2B/B2C + armadilha de conta interna/teste)
  - {prefix}.dim_produtos   (Dimensão de produtos e categorias + margem alvo)
  - {prefix}.dim_vendedores (Dimensão comercial por regional)
  - {prefix}.fct_pedidos    (Tabela fato de pedidos comerciais — 1 linha por pedido)

Armadilhas de negócio propositais incluídas para testar a evolução da acurácia do Genie:
  1. Status mistos na fato: pedidos 'Faturado', 'Cancelado', 'Devolvido' e 'Pendente'.
     -> Receita líquida oficial considera APENAS status_pedido = 'Faturado'.
  2. Duas datas com semântica distinta: data_pedido (criação) vs competencia_faturamento (YYYY-MM).
     -> Pedidos criados nos últimos 3 dias do mês são faturados na competência seguinte!
  3. Valor bruto vs desconto vs valor líquido:
     -> Pedidos com desconto > 15% exigem alçada de aprovação especial.
  4. Grão de pedido vs cliente (fan-out):
     -> Múltiplos pedidos por cliente; contar clientes ativos exige COUNT(DISTINCT id_cliente).
  5. Clientes de teste/interno:
     -> ~3% dos clientes possuem segmento = 'Interno' (devem ser claramente distinguidos).
  6. Colunas técnicas ruidosas:
     -> id_pedido, _ingestion_ts e hash_lote (devem receber exclude: true no Genie Space).
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

CATALOG = "{catalog}"
SCHEMA = "{schema}"
PREFIX = f"{{CATALOG}}.{{SCHEMA}}"
NUM_CLIENTES = {rows_clientes}
NUM_PEDIDOS = {rows_pedidos}

spark = SparkSession.builder.getOrCreate()

spark.sql(f"CREATE CATALOG IF NOT EXISTS {{CATALOG}}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {{PREFIX}}")

# ---------------------------------------------------------------------------
# 1. Dimensão Clientes ({prefix}.dim_clientes)
# ---------------------------------------------------------------------------
df_clientes = (
    spark.range(1, NUM_CLIENTES + 1)
    .withColumn("id_cliente", F.col("id").cast("INT"))
    .withColumn(
        "segmento",
        F.when(F.col("id") % 33 == 0, F.lit("Interno"))
        .when(F.col("id") % 5 == 0, F.lit("Enterprise"))
        .when(F.col("id") % 3 == 0, F.lit("Mid-Market"))
        .when(F.col("id") % 2 == 0, F.lit("SMB"))
        .otherwise(F.lit("Varejo")),
    )
    .withColumn(
        "porte_empresa",
        F.when(F.col("segmento") == "Enterprise", F.lit("Grande"))
        .when(F.col("segmento") == "Mid-Market", F.lit("Médio"))
        .otherwise(F.lit("Pequeno")),
    )
    .withColumn(
        "uf",
        F.element_at(
            F.array(
                F.lit("SP"), F.lit("RJ"), F.lit("MG"), F.lit("RS"),
                F.lit("PR"), F.lit("BA"), F.lit("PE"), F.lit("DF"), F.lit("AM"),
            ),
            ((F.col("id") % 9) + 1).cast("INT"),
        ),
    )
    .withColumn(
        "nome_cliente",
        F.concat(
            F.when(F.col("segmento") == "Interno", F.lit("QA_INTERNO_"))
            .when(F.col("segmento") == "Enterprise", F.lit("Corporação "))
            .when(F.col("segmento") == "Mid-Market", F.lit("Grupo "))
            .otherwise(F.lit("Comercial ")),
            F.lpad(F.col("id").cast("STRING"), 4, "0"),
            F.lit(" Ltda"),
        ),
    )
    .withColumn(
        "data_cadastro",
        F.date_add(F.lit("2024-01-01").cast("DATE"), (F.col("id") * 3 % 800).cast("INT")),
    )
    .drop("id")
)

df_clientes.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{{PREFIX}}.dim_clientes"
)

# ---------------------------------------------------------------------------
# 2. Dimensão Produtos ({prefix}.dim_produtos)
# ---------------------------------------------------------------------------
produtos_seed = [
    (1, "Analytics Enterprise Suite", "Software", 24000.00, 0.78),
    (2, "Data Lakehouse Connector", "Software", 12500.00, 0.72),
    (3, "Pacote Consultoria BI", "Serviços", 18000.00, 0.55),
    (4, "Treinamento Databricks Pro", "Educação", 6500.00, 0.68),
    (5, "Suporte Premium 24x7", "Serviços", 9800.00, 0.62),
    (6, "Módulo Governança UC", "Software", 15000.00, 0.75),
]
df_produtos = spark.createDataFrame(
    produtos_seed,
    ["id_produto", "nome_produto", "categoria_produto", "preco_lista", "margem_alvo_pct"],
)
df_produtos.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{{PREFIX}}.dim_produtos"
)

# ---------------------------------------------------------------------------
# 3. Dimensão Vendedores ({prefix}.dim_vendedores)
# ---------------------------------------------------------------------------
vendedores_seed = [
    (1, "Ana Paula Costa", "Sudeste", "Inside Sales"),
    (2, "Bruno Henrique Silva", "Sul", "Parceiros"),
    (3, "Carla Mendes Rocha", "Nordeste", "Inside Sales"),
    (4, "Diego Almeida Lima", "Sudeste", "E-commerce"),
    (5, "Fernanda Oliveira", "Centro-Oeste", "Marketplace"),
    (6, "Gustavo Pereira", "Norte", "Parceiros"),
]
df_vendedores = spark.createDataFrame(
    vendedores_seed,
    ["id_vendedor", "nome_vendedor", "regional_vendedor", "equipe_canal"],
)
df_vendedores.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{{PREFIX}}.dim_vendedores"
)

# ---------------------------------------------------------------------------
# 4. Tabela Fato Pedidos ({prefix}.fct_pedidos) — com armadilhas de negócio
# ---------------------------------------------------------------------------
df_base = (
    spark.range(1, NUM_PEDIDOS + 1)
    .withColumn("id_pedido", F.concat(F.lit("PED-"), F.lpad(F.col("id").cast("STRING"), 7, "0")))
    .withColumn("id_cliente", (((F.col("id") * 17) % NUM_CLIENTES) + 1).cast("INT"))
    .withColumn("id_produto", (((F.col("id") * 7) % 6) + 1).cast("INT"))
    .withColumn("id_vendedor", (((F.col("id") * 5) % 6) + 1).cast("INT"))
    # Datas entre 2025-01-01 e 2026-06-30
    .withColumn(
        "data_pedido",
        F.date_add(F.lit("2025-01-01").cast("DATE"), ((F.col("id") * 11) % 545).cast("INT")),
    )
    # Armadilha #2: pedidos criados após dia 28 entram na competência contábil do mês seguinte
    .withColumn(
        "competencia_faturamento",
        F.date_format(
            F.when(
                F.dayofmonth(F.col("data_pedido")) >= 29,
                F.add_months(F.col("data_pedido"), 1),
            ).otherwise(F.col("data_pedido")),
            "yyyy-MM",
        ),
    )
    # Armadilha #1: status mistos (78% Faturado, 10% Cancelado, 7% Devolvido, 5% Pendente)
    .withColumn("r_status", (F.col("id") * 31) % 100)
    .withColumn(
        "status_pedido",
        F.when(F.col("r_status") < 78, F.lit("Faturado"))
        .when(F.col("r_status") < 88, F.lit("Cancelado"))
        .when(F.col("r_status") < 95, F.lit("Devolvido"))
        .otherwise(F.lit("Pendente")),
    )
    .withColumn(
        "canal_venda",
        F.element_at(
            F.array(F.lit("E-commerce"), F.lit("Inside Sales"), F.lit("Marketplace"), F.lit("Parceiros")),
            ((F.col("id") % 4) + 1).cast("INT"),
        ),
    )
    .withColumn(
        "regiao",
        F.element_at(
            F.array(
                F.lit("Sudeste"), F.lit("Sul"), F.lit("Nordeste"),
                F.lit("Centro-Oeste"), F.lit("Norte"),
            ),
            ((F.col("id") % 5) + 1).cast("INT"),
        ),
    )
    .withColumn(
        "forma_pagamento",
        F.element_at(
            F.array(
                F.lit("Pix"), F.lit("Cartão Corporativo"),
                F.lit("Boleto"), F.lit("Transferência"),
            ),
            (((F.col("id") * 3) % 4) + 1).cast("INT"),
        ),
    )
    # Armadilha #3: valor_bruto vs valor_desconto vs valor_liquido (incluindo descontos > 15%)
    .withColumn(
        "valor_bruto",
        F.round(F.lit(1500.0) + ((F.col("id") * 257) % 28500).cast("DOUBLE"), 2),
    )
    .withColumn(
        "pct_desconto_aplicado",
        F.when(F.col("id") % 19 == 0, F.lit(0.22))  # desconto acima de 15% (alçada diretoria)
        .when(F.col("id") % 5 == 0, F.lit(0.12))
        .when(F.col("id") % 2 == 0, F.lit(0.05))
        .otherwise(F.lit(0.00)),
    )
    .withColumn("valor_desconto", F.round(F.col("valor_bruto") * F.col("pct_desconto_aplicado"), 2))
    .withColumn("valor_liquido", F.round(F.col("valor_bruto") - F.col("valor_desconto"), 2))
    # Armadilha #6: colunas técnicas que devem ser ocultadas no Genie
    .withColumn("_ingestion_ts", F.current_timestamp())
    .withColumn("hash_lote", F.sha2(F.col("id_pedido"), 256))
    .drop("id", "r_status", "pct_desconto_aplicado")
)

df_base.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{{PREFIX}}.fct_pedidos"
)

print(f"Base Star Schema criada com sucesso em {{PREFIX}}!")
print("Próximo passo: execute 02_uc_comments.sql e 03_trusted_sql_functions.sql no SQL Warehouse.")
'''


def build_trusted_sql_functions_ddl(catalog: str, schema: str) -> str:
    """Gera DDL de SQL Functions (Trusted Assets) no Unity Catalog para o esquema estrela de vendas."""
    cat_q = quote_ident(validate_uc_identifier(catalog, "catalog"))
    sch_q = quote_ident(validate_uc_identifier(schema, "schema"))
    prefix = f"{cat_q}.{sch_q}"

    return f"""-- Databricks GenieOps — SQL Functions (Trusted Assets) no Unity Catalog
-- Destino: {prefix}
-- Registre estas funções no Unity Catalog e referencie-as em instructions.sql_functions no Genie Space.

CREATE OR REPLACE FUNCTION {prefix}.fn_receita_liquida_periodo(
  p_comp_inicio STRING COMMENT 'Mês de competência inicial no formato YYYY-MM (ex.: 2026-01)',
  p_comp_fim STRING COMMENT 'Mês de competência final no formato YYYY-MM (ex.: 2026-03)'
)
RETURNS TABLE (
  regiao STRING,
  canal_venda STRING,
  pedidos_faturados BIGINT,
  receita_liquida DOUBLE,
  ticket_medio DOUBLE
)
COMMENT 'Trusted Asset oficial: calcula receita líquida faturada e ticket médio por região e canal no intervalo de competência, filtrando exclusivamente pedidos Faturados e excluindo contas internas.'
RETURN
  SELECT
    p.regiao,
    p.canal_venda,
    COUNT(p.id_pedido) AS pedidos_faturados,
    ROUND(SUM(p.valor_liquido), 2) AS receita_liquida,
    ROUND(AVG(p.valor_liquido), 2) AS ticket_medio
  FROM {prefix}.fct_pedidos p
  JOIN {prefix}.dim_clientes c ON p.id_cliente = c.id_cliente
  WHERE p.competencia_faturamento BETWEEN p_comp_inicio AND p_comp_fim
    AND p.status_pedido = 'Faturado'
    AND c.segmento <> 'Interno'
  GROUP BY p.regiao, p.canal_venda;

CREATE OR REPLACE FUNCTION {prefix}.fn_taxa_cancelamento_regiao(
  p_competencia STRING COMMENT 'Competência contábil YYYY-MM (ex.: 2026-01)'
)
RETURNS TABLE (
  regiao STRING,
  total_pedidos BIGINT,
  pedidos_cancelados BIGINT,
  taxa_cancelamento_pct DOUBLE
)
COMMENT 'Trusted Asset oficial: calcula a taxa não-aditiva de cancelamento percentual por região para uma competência contábil.'
RETURN
  SELECT
    p.regiao,
    COUNT(*) AS total_pedidos,
    SUM(CASE WHEN p.status_pedido = 'Cancelado' THEN 1 ELSE 0 END) AS pedidos_cancelados,
    ROUND(
      SUM(CASE WHEN p.status_pedido = 'Cancelado' THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0),
      2
    ) AS taxa_cancelamento_pct
  FROM {prefix}.fct_pedidos p
  WHERE p.competencia_faturamento = p_competencia
  GROUP BY p.regiao;

CREATE OR REPLACE FUNCTION {prefix}.fn_top_clientes_segmento(
  p_segmento STRING COMMENT 'Segmento do cliente (Enterprise, Mid-Market, SMB, Varejo)',
  p_ano STRING COMMENT 'Ano de faturamento YYYY (ex.: 2026)',
  p_limite INT DEFAULT 10 COMMENT 'Quantidade máxima de clientes no ranking'
)
RETURNS TABLE (
  nome_cliente STRING,
  uf STRING,
  pedidos_faturados BIGINT,
  receita_liquida DOUBLE
)
COMMENT 'Trusted Asset oficial: retorna o ranking dos maiores clientes de um segmento em um ano considerando apenas pedidos Faturados.'
RETURN
  WITH ranked AS (
    SELECT
      c.nome_cliente,
      c.uf,
      COUNT(p.id_pedido) AS pedidos_faturados,
      ROUND(SUM(p.valor_liquido), 2) AS receita_liquida,
      ROW_NUMBER() OVER (ORDER BY SUM(p.valor_liquido) DESC) AS rn
    FROM {prefix}.fct_pedidos p
    JOIN {prefix}.dim_clientes c ON p.id_cliente = c.id_cliente
    WHERE c.segmento = p_segmento
      AND LEFT(p.competencia_faturamento, 4) = p_ano
      AND p.status_pedido = 'Faturado'
    GROUP BY c.nome_cliente, c.uf
  )
  SELECT nome_cliente, uf, pedidos_faturados, receita_liquida
  FROM ranked
  WHERE rn <= p_limite;
"""


def build_curation_playbook_md(catalog: str, schema: str, space_name: str = "exemplo_vendas") -> str:
    """Gera o guia passo-a-passo de curadoria progressiva (Rodada 0 -> Rodada 4 + Delta + Docs)."""
    return f"""# Playbook de Curadoria Progressiva — Genie Space (`{space_name}`)

Este guia implementa de ponta a ponta o fluxo experimental de curadoria em camadas para medir objetivamente a evolução da acurácia no Unity Catalog (`{catalog}.{schema}`).

---

## Etapa 0 — Preparar Base Fictícia Star Schema & Governança no Unity Catalog

1. **Criar tabelas Delta com armadilhas de negócio:** execute `01_seed_star_schema.py` no Databricks (Serverless Notebook ou Job).
2. **Aplicar COMMENTs em tabelas e colunas no Unity Catalog:** execute `02_uc_comments.sql` (também regenerável para qualquer Space via `genieops uc-comments {space_name}`).
3. **Registrar Trusted Assets (SQL Functions):** execute `03_trusted_sql_functions.sql` no SQL Warehouse.

---

## Rodadas Progressivas de Curadoria & Benchmark

Cada rodada aplica **uma camada adicional** de contexto, faz deploy versionado e registra a acurácia rotulada em `.genieops/history.db`:

### Rodada 0 — Baseline (Somente Tabelas)
- Mantenha `instructions.yaml` vazio (sem `text_instructions`, `example_question_sqls`, `sql_snippets` ou `sql_functions`).
```powershell
genieops deploy {space_name} --env dev --skip-lint
genieops benchmark {space_name} --env dev --mode live --expand-paraphrases --label "Rodada 0 - Só tabelas"
```

### Rodada 1 — + COMMENTs no UC & `column_configs` (Sinônimos + Entity Matching)
- Aplique `02_uc_comments.sql` no Unity Catalog e preencha `sources.yaml` (`description`, `synonyms`, `enable_entity_matching`, `exclude`).
```powershell
genieops deploy {space_name} --env dev
genieops benchmark {space_name} --env dev --mode live --expand-paraphrases --label "Rodada 1 - +UC Comments e Column Configs"
```

### Rodada 2 — + Instruções em Texto (`text_instructions`) + Joins & Snippets
- Adicione as regras globais concisas em `instructions.yaml` (`text_instructions`, `join_specs`, `sql_snippets`).
```powershell
genieops deploy {space_name} --env dev
genieops benchmark {space_name} --env dev --mode live --expand-paraphrases --label "Rodada 2 - +Text Instructions"
```

### Rodada 3 — + SQLs de Exemplo (`example_question_sqls`)
- Adicione exemplos representativos por padrão de consulta (o `genieops lint --strict` garante 0% de Benchmark Leakage).
```powershell
genieops lint {space_name} --strict
genieops deploy {space_name} --env dev
genieops benchmark {space_name} --env dev --mode live --expand-paraphrases --label "Rodada 3 - +SQLs de Exemplo"
```

### Rodada 4 — + SQL Functions / Trusted Assets (`sql_functions`)
- Referencie as 3 UDFs governadas (`fn_receita_liquida_periodo`, `fn_taxa_cancelamento_regiao`, `fn_top_clientes_segmento`) em `instructions.yaml`.
```powershell
genieops lint {space_name} --validate-sql --env dev --strict
genieops deploy {space_name} --env dev
genieops benchmark {space_name} --env dev --mode live --expand-paraphrases --label "Rodada 4 - +SQL Functions (Trusted Assets)"
```

---

## Etapa Final — Persistir Rodadas em Tabela Delta & Gerar Relatório de Evolução

1. **Registrar todas as rodadas em tabelas Delta no Unity Catalog (`genie_opt_runs`, `genie_opt_eval_results`, etc.):**
```powershell
# Preview SQL seguro (dry-run):
genieops export-delta {space_name} --catalog {catalog} --schema genieops_audit

# Executar no SQL Warehouse (opt-in explícito):
genieops export-delta {space_name} --catalog {catalog} --schema genieops_audit --execute
```

2. **Gerar documentação completa com a tabela de evolução da acurácia por rodada:**
```powershell
genieops docs {space_name}
```
Os artefatos gerados (`RELATORIO_EXECUTIVO.md`, `relatorio_executivo.html`, `SPEC_TECNICA.md` e `GUIA_USUARIO.md`) incluem a **Tabela de Evolução da Acurácia por Rodada** com rótulo, delta (pp), taxa de acerto e latência P50/P95.
"""


def generate_star_schema_kit(
    catalog: str,
    schema: str,
    output_dir: Path,
    *,
    bundle: SpaceBundle | None = None,
    rows_pedidos: int = 5000,
    rows_clientes: int = 300,
) -> dict[str, Path]:
    """Gera todos os artefatos do kit de estudo/curadoria Star Schema no diretório de destino."""
    output_dir.mkdir(parents=True, exist_ok=True)
    cat_clean = validate_uc_identifier(catalog, "catalog")
    sch_clean = validate_uc_identifier(schema, "schema")

    seed_path = output_dir / "01_seed_star_schema.py"
    seed_path.write_text(
        build_star_schema_seed_script(
            cat_clean,
            sch_clean,
            rows_pedidos=rows_pedidos,
            rows_clientes=rows_clientes,
        ),
        encoding="utf-8",
    )

    comments_path = output_dir / "02_uc_comments.sql"
    if bundle is not None:
        comments_sql = generate_uc_comments_sql(bundle, include_metric_views=False)
    else:
        prefix = f"{quote_ident(cat_clean)}.{quote_ident(sch_clean)}"
        comments_sql = (
            f"-- COMMENTs base para o esquema estrela em {prefix}\n"
            f"COMMENT ON TABLE {prefix}.fct_pedidos IS 'Tabela fato granular de pedidos comerciais (1 linha por pedido). Receita oficial usa status_pedido = Faturado.';\n"
            f"COMMENT ON TABLE {prefix}.dim_clientes IS 'Dimensão de clientes B2B e B2C com segmento, porte empresarial, UF e data de cadastro.';\n"
            f"COMMENT ON TABLE {prefix}.dim_produtos IS 'Dimensão de produtos, categorias comerciais, preço de lista e margem alvo.';\n"
            f"COMMENT ON TABLE {prefix}.dim_vendedores IS 'Dimensão de vendedores e equipe comercial por regional.';\n"
        )
    comments_path.write_text(comments_sql, encoding="utf-8")

    udfs_path = output_dir / "03_trusted_sql_functions.sql"
    udfs_path.write_text(build_trusted_sql_functions_ddl(cat_clean, sch_clean), encoding="utf-8")

    playbook_path = output_dir / "GUIA_RODADAS_CURADORIA.md"
    space_name = bundle.space.name if bundle is not None else "exemplo_vendas"
    playbook_path.write_text(
        build_curation_playbook_md(cat_clean, sch_clean, space_name=space_name),
        encoding="utf-8",
    )

    return {
        "seed_script": seed_path,
        "uc_comments": comments_path,
        "trusted_sql_functions": udfs_path,
        "playbook": playbook_path,
    }
