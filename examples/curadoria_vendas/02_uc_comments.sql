-- Databricks GenieOps — COMMENTs semânticos no Unity Catalog (exemplo_vendas)
-- Space: Comercial & Receita Corporativa AI-BI
-- Script revisável e idempotente para aplicar governança semântica diretamente no catálogo UC.

-- Fonte: analytics_dev.sales_gold.fct_pedidos
COMMENT ON TABLE analytics_dev.sales_gold.fct_pedidos IS 'Tabela fato granular de pedidos comerciais (1 linha por pedido), incluindo competência de faturamento, receita líquida, desconto, canal e status.';
ALTER TABLE analytics_dev.sales_gold.fct_pedidos ALTER COLUMN `id_pedido` COMMENT 'Coluna técnica/interna (excluída do contexto analítico do Genie).';
ALTER TABLE analytics_dev.sales_gold.fct_pedidos ALTER COLUMN `_ingestion_ts` COMMENT 'Coluna técnica/interna (excluída do contexto analítico do Genie).';
ALTER TABLE analytics_dev.sales_gold.fct_pedidos ALTER COLUMN `id_cliente` COMMENT 'Chave estrangeira do cliente para junção com dim_clientes.';
ALTER TABLE analytics_dev.sales_gold.fct_pedidos ALTER COLUMN `data_pedido` COMMENT 'Data cronológica de criação do pedido pelo cliente no formato YYYY-MM-DD. Sinônimos de negócio: data da compra, data da venda.';
ALTER TABLE analytics_dev.sales_gold.fct_pedidos ALTER COLUMN `competencia_faturamento` COMMENT 'Mês de competência contábil do faturamento no formato YYYY-MM. Utilize sempre esta coluna para fechamento mensal de receita. Sinônimos de negócio: mês de faturamento, competência, período contábil.';
ALTER TABLE analytics_dev.sales_gold.fct_pedidos ALTER COLUMN `status_pedido` COMMENT 'Situação operacional do pedido (Faturado, Cancelado, Pendente, Devolvido). Sinônimos de negócio: status, situação do pedido.';
ALTER TABLE analytics_dev.sales_gold.fct_pedidos ALTER COLUMN `canal_venda` COMMENT 'Canal comercial de origem da venda (E-commerce, Inside Sales, Marketplace, Parceiros). Sinônimos de negócio: canal, origem da venda.';
ALTER TABLE analytics_dev.sales_gold.fct_pedidos ALTER COLUMN `regiao` COMMENT 'Macrorregião geográfica de atendimento comercial (Sudeste, Sul, Nordeste, Centro-Oeste, Norte). Sinônimos de negócio: região comercial, praça.';
ALTER TABLE analytics_dev.sales_gold.fct_pedidos ALTER COLUMN `forma_pagamento` COMMENT 'Meio de pagamento utilizado no pedido (Pix, Cartão Corporativo, Boleto, Transferência). Sinônimos de negócio: meio de pagamento, pagamento.';
ALTER TABLE analytics_dev.sales_gold.fct_pedidos ALTER COLUMN `valor_bruto` COMMENT 'Valor bruto do pedido antes de descontos em Reais (BRL).';
ALTER TABLE analytics_dev.sales_gold.fct_pedidos ALTER COLUMN `valor_desconto` COMMENT 'Valor total de desconto concedido no pedido em Reais (BRL).';
ALTER TABLE analytics_dev.sales_gold.fct_pedidos ALTER COLUMN `valor_liquido` COMMENT 'Receita líquida faturada do pedido (valor_bruto menos valor_desconto) em Reais (BRL). Sinônimos de negócio: receita líquida, faturamento líquido, net revenue.';

-- Fonte: analytics_dev.sales_gold.dim_clientes
COMMENT ON TABLE analytics_dev.sales_gold.dim_clientes IS 'Dimensão cadastral de clientes B2B e B2C com segmento, porte empresarial, UF e data de aquisição.';
ALTER TABLE analytics_dev.sales_gold.dim_clientes ALTER COLUMN `id_cliente` COMMENT 'Identificador único do cliente (chave primária de dim_clientes).';
ALTER TABLE analytics_dev.sales_gold.dim_clientes ALTER COLUMN `nome_cliente` COMMENT 'Razão social ou nome fantasia do cliente. Sinônimos de negócio: cliente, conta.';
ALTER TABLE analytics_dev.sales_gold.dim_clientes ALTER COLUMN `segmento` COMMENT 'Segmento de atuação do cliente (Enterprise, Mid-Market, SMB, Varejo). Sinônimos de negócio: segmento de cliente, carteira.';
ALTER TABLE analytics_dev.sales_gold.dim_clientes ALTER COLUMN `porte_empresa` COMMENT 'Porte empresarial classificado por faixa de faturamento (Grande, Médio, Pequeno). Sinônimos de negócio: porte.';
ALTER TABLE analytics_dev.sales_gold.dim_clientes ALTER COLUMN `uf` COMMENT 'Sigla da unidade federativa (estado) da sede do cliente (ex. SP, RJ, MG, RS). Sinônimos de negócio: estado.';
ALTER TABLE analytics_dev.sales_gold.dim_clientes ALTER COLUMN `data_cadastro` COMMENT 'Data de aquisição/cadastro inicial do cliente (YYYY-MM-DD).';
