-- Databricks GenieOps — SQL Functions (Trusted Assets) no Unity Catalog
-- Destino: analytics_dev.sales_gold
-- Registre estas funções no Unity Catalog e referencie-as em instructions.sql_functions no Genie Space.

CREATE OR REPLACE FUNCTION analytics_dev.sales_gold.fn_receita_liquida_periodo(
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
  FROM analytics_dev.sales_gold.fct_pedidos p
  JOIN analytics_dev.sales_gold.dim_clientes c ON p.id_cliente = c.id_cliente
  WHERE p.competencia_faturamento BETWEEN p_comp_inicio AND p_comp_fim
    AND p.status_pedido = 'Faturado'
    AND c.segmento <> 'Interno'
  GROUP BY p.regiao, p.canal_venda;

CREATE OR REPLACE FUNCTION analytics_dev.sales_gold.fn_taxa_cancelamento_regiao(
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
  FROM analytics_dev.sales_gold.fct_pedidos p
  WHERE p.competencia_faturamento = p_competencia
  GROUP BY p.regiao;

CREATE OR REPLACE FUNCTION analytics_dev.sales_gold.fn_top_clientes_segmento(
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
  SELECT
    c.nome_cliente,
    c.uf,
    COUNT(p.id_pedido) AS pedidos_faturados,
    ROUND(SUM(p.valor_liquido), 2) AS receita_liquida
  FROM analytics_dev.sales_gold.fct_pedidos p
  JOIN analytics_dev.sales_gold.dim_clientes c ON p.id_cliente = c.id_cliente
  WHERE c.segmento = p_segmento
    AND LEFT(p.competencia_faturamento, 4) = p_ano
    AND p.status_pedido = 'Faturado'
  GROUP BY c.nome_cliente, c.uf
  ORDER BY receita_liquida DESC
  LIMIT p_limite;
