# Databricks notebook source
"""
Databricks GenieOps — Gerador de Base Fictícia em Esquema Estrela (com Armadilhas de Negócio)
=============================================================================================
Cria tabelas Delta no Unity Catalog (analytics_dev.sales_gold) prontas para curadoria progressiva de Genie Space:
  - analytics_dev.sales_gold.dim_clientes   (Dimensão de clientes B2B/B2C + armadilha de conta interna/teste)
  - analytics_dev.sales_gold.dim_produtos   (Dimensão de produtos e categorias + margem alvo)
  - analytics_dev.sales_gold.dim_vendedores (Dimensão comercial por regional)
  - analytics_dev.sales_gold.fct_pedidos    (Tabela fato de pedidos comerciais — 1 linha por pedido)

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

CATALOG = "analytics_dev"
SCHEMA = "sales_gold"
PREFIX = f"{CATALOG}.{SCHEMA}"
NUM_CLIENTES = 300
NUM_PEDIDOS = 5000

spark = SparkSession.builder.getOrCreate()

spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {PREFIX}")

# ---------------------------------------------------------------------------
# 1. Dimensão Clientes (analytics_dev.sales_gold.dim_clientes)
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
    f"{PREFIX}.dim_clientes"
)

# ---------------------------------------------------------------------------
# 2. Dimensão Produtos (analytics_dev.sales_gold.dim_produtos)
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
    f"{PREFIX}.dim_produtos"
)

# ---------------------------------------------------------------------------
# 3. Dimensão Vendedores (analytics_dev.sales_gold.dim_vendedores)
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
    f"{PREFIX}.dim_vendedores"
)

# ---------------------------------------------------------------------------
# 4. Tabela Fato Pedidos (analytics_dev.sales_gold.fct_pedidos) — com armadilhas de negócio
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
    f"{PREFIX}.fct_pedidos"
)

print(f"Base Star Schema criada com sucesso em {PREFIX}!")
print("Próximo passo: execute 02_uc_comments.sql e 03_trusted_sql_functions.sql no SQL Warehouse.")
