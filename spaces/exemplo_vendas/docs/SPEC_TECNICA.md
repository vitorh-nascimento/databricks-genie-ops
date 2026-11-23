# Especificação Técnica — Comercial & Receita Corporativa AI-BI

> **Gerado automaticamente pelo Databricks GenieOps** em 2026-11-23 11:14 UTC
> **Identificador do Space:** `exemplo_vendas` | **Responsável:** Data & Analytics — Squad Comercial | **Health Score:** **100/100**

---

## 1. Visão Geral & Escopo

- **Descrição:** Genie Space curado para análise comercial corporativa, receita líquida, descontos, desempenho por canal/região, carteira de clientes B2B/B2C e políticas comerciais (Agent Mode).
- **Público-Alvo:** Diretoria Comercial, RevOps, Analistas de BI e Executivos de Contas
- **Domínios Cobertos:** Pedidos & Faturamento, Carteira de Clientes, KPIs Comerciais Governados, Políticas Comerciais & Descontos

### Arquitetura Semântica

```mermaid
flowchart LR
    User(["Usuário de Negócio"]) -->|Linguagem Natural| Genie["Databricks Genie Agent<br/>Comercial & Receita Corporativa AI-BI"]
    Genie -->|SQL| T1[("Tabela: fct_pedidos")]
    Genie -->|SQL| T2[("Tabela: dim_clientes")]
    Genie -->|MEASURE()| MV1[("Metric View: mv_kpis_comerciais")]
    Genie -->|Agent Mode Docs| V1["Volume: politicas_comerciais"]
    Genie -->|Trusted Asset| FN1(["UDF: fn_receita_liquida_periodo"])
    Genie -->|Trusted Asset| FN2(["UDF: fn_taxa_cancelamento_regiao"])
    Genie -->|Trusted Asset| FN3(["UDF: fn_top_clientes_segmento"])
```

---

## 2. Ambientes Configurados

| Ambiente | Profile CLI | Catalog | Schema | Parent Path |
| :--- | :--- | :--- | :--- | :--- |
| `dev` | `dev-workspace` | `analytics_dev` | `sales_gold` | `/Workspace/Shared/genie_spaces/dev/exemplo_vendas` |
| `qa` | `qa-workspace` | `analytics_qa` | `sales_gold` | `/Workspace/Shared/genie_spaces/qa/exemplo_vendas` |
| `prod` | `prod-workspace` | `analytics_prod` | `sales_gold` | `/Workspace/Shared/genie_spaces/prod/exemplo_vendas` |

---

## 3. Catálogo de Fontes de Dados (Unity Catalog)

### 3.1. Tabelas
#### `analytics_dev.sales_gold.fct_pedidos`
Tabela fato granular de pedidos comerciais (1 linha por pedido), incluindo competência de faturamento, receita líquida, desconto, canal e status.

| Coluna | Descrição | Sinônimos | Entity Matching | Format Assist | Excluída |
| :--- | :--- | :--- | :---: | :---: | :---: |
| `id_pedido` | — | — | Não | Não | Sim |
| `_ingestion_ts` | — | — | Não | Não | Sim |
| `id_cliente` | Chave estrangeira do cliente para junção com dim_clientes. | — | Não | Não | Não |
| `data_pedido` | Data cronológica de criação do pedido pelo cliente no formato YYYY-MM-DD. | data da compra, data da venda | Não | Não | Não |
| `competencia_faturamento` | Mês de competência contábil do faturamento no formato YYYY-MM. Utilize sempre esta coluna para fechamento mensal de receita. | mês de faturamento, competência, período contábil | Sim | Sim | Não |
| `status_pedido` | Situação operacional do pedido (Faturado, Cancelado, Pendente, Devolvido). | status, situação do pedido | Sim | Sim | Não |
| `canal_venda` | Canal comercial de origem da venda (E-commerce, Inside Sales, Marketplace, Parceiros). | canal, origem da venda | Sim | Sim | Não |
| `regiao` | Macrorregião geográfica de atendimento comercial (Sudeste, Sul, Nordeste, Centro-Oeste, Norte). | região comercial, praça | Sim | Sim | Não |
| `forma_pagamento` | Meio de pagamento utilizado no pedido (Pix, Cartão Corporativo, Boleto, Transferência). | meio de pagamento, pagamento | Sim | Sim | Não |
| `valor_bruto` | Valor bruto do pedido antes de descontos em Reais (BRL). | — | Não | Não | Não |
| `valor_desconto` | Valor total de desconto concedido no pedido em Reais (BRL). | — | Não | Não | Não |
| `valor_liquido` | Receita líquida faturada do pedido (valor_bruto menos valor_desconto) em Reais (BRL). | receita líquida, faturamento líquido, net revenue | Não | Não | Não |

#### `analytics_dev.sales_gold.dim_clientes`
Dimensão cadastral de clientes B2B e B2C com segmento, porte empresarial, UF e data de aquisição.

| Coluna | Descrição | Sinônimos | Entity Matching | Format Assist | Excluída |
| :--- | :--- | :--- | :---: | :---: | :---: |
| `id_cliente` | Identificador único do cliente (chave primária de dim_clientes). | — | Não | Não | Não |
| `nome_cliente` | Razão social ou nome fantasia do cliente. | cliente, conta | Não | Não | Não |
| `segmento` | Segmento de atuação do cliente (Enterprise, Mid-Market, SMB, Varejo). | segmento de cliente, carteira | Sim | Sim | Não |
| `porte_empresa` | Porte empresarial classificado por faixa de faturamento (Grande, Médio, Pequeno). | porte | Sim | Sim | Não |
| `uf` | Sigla da unidade federativa (estado) da sede do cliente (ex. SP, RJ, MG, RS). | estado | Sim | Sim | Não |
| `data_cadastro` | Data de aquisição/cadastro inicial do cliente (YYYY-MM-DD). | — | Não | Não | Não |


### 3.2. Metric Views Governadas
#### `analytics_dev.sales_gold.mv_kpis_comerciais`
Metric View governada contendo indicadores oficiais de receita líquida, ticket médio, taxa de desconto e volume de pedidos faturados. Use MEASURE() para consultar suas medidas.

| Dimensão / Medida | Descrição | Sinônimos | Entity Matching |
| :--- | :--- | :--- | :---: |
| `competencia_faturamento` | Mês de competência contábil (YYYY-MM). | — | Sim |
| `regiao` | Macrorregião comercial. | — | Sim |
| `canal_venda` | Canal comercial de vendas. | — | Sim |
| `receita_liquida_total` | Medida governada de receita líquida de pedidos faturados. | faturamento oficial, receita oficial | Não |
| `ticket_medio` | Medida governada de ticket médio por pedido faturado. | — | Não |
| `taxa_desconto_pct` | Percentual médio de desconto concedido sobre o valor bruto. | — | Não |


### 3.3. UC Volumes (Documentos para Agent Mode)
| Caminho no Unity Catalog | Descrição & Regra de Roteamento |
| :--- | :--- |
| `/Volumes/analytics_dev/sales_docs/politicas_comerciais` | Manual de política comercial, alçadas de aprovação de desconto, regras de devolução e SLA de faturamento (PDF/MD). Consultar via Agent Mode e citar o arquivo fonte. |

---

## 4. Relacionamentos (`join_specs`)

| Esquerda | Direita | Relacionamento | Condição SQL |
| :--- | :--- | :---: | :--- |
| `analytics_dev.sales_gold.fct_pedidos` (`fct_pedidos`) | `analytics_dev.sales_gold.dim_clientes` (`dim_clientes`) | `MANY_TO_ONE` | ``fct_pedidos`.`id_cliente` = `dim_clientes`.`id_cliente`` |

---

## 5. SQL Snippets Reutilizáveis

### Medidas (`measures`)
| Alias | Nome de Exibição | Expressão SQL | Sinônimos |
| :--- | :--- | :--- | :--- |
| `receita_liquida_faturada` | Receita Líquida Faturada | `SUM(CASE WHEN fct_pedidos.status_pedido = 'Faturado' THEN fct_pedidos.valor_liquido ELSE 0 END)` | faturamento confirmado, receita realizada |
| `taxa_cancelamento_pct` | Taxa de Cancelamento (%) | `ROUND(SUM(CASE WHEN fct_pedidos.status_pedido = 'Cancelado' THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(fct_pedidos.id_pedido), 0), 2)` | percentual de cancelamento, churn de pedidos |

### Filtros (`filters`)
| Nome de Exibição | Expressão SQL | Sinônimos |
| :--- | :--- | :--- |
| Pedidos Faturados | `fct_pedidos.status_pedido = 'Faturado'` | vendas efetivas, pedidos válidos |
| Pedidos Enterprise | `dim_clientes.segmento = 'Enterprise'` | grandes contas |

### Expressões (`expressions`)
| Alias | Nome de Exibição | Expressão SQL |
| :--- | :--- | :--- |
| `ano_faturamento` | Ano de Faturamento | `LEFT(fct_pedidos.competencia_faturamento, 4)` |

---

## 6. SQL Functions / Trusted Assets (`sql_functions`)

| Identificador (Unity Catalog) | Descrição |
| :--- | :--- |
| `analytics_dev.sales_gold.fn_receita_liquida_periodo` | Trusted Asset oficial: receita líquida faturada e ticket médio por região e canal num intervalo de competência (excluindo contas internas). |
| `analytics_dev.sales_gold.fn_taxa_cancelamento_regiao` | Trusted Asset oficial: taxa percentual não-aditiva de cancelamento por região numa competência contábil. |
| `analytics_dev.sales_gold.fn_top_clientes_segmento` | Trusted Asset oficial: ranking dos maiores clientes faturados de um segmento em um ano. |

---

## 7. Instruções Globais (`text_instructions`)

```text
Responda em português objetivo, informando o período de competência analisado e valores em Reais (R$).
Para perguntas de KPIs executivos consolidados, prefira a Metric View mv_kpis_comerciais usando MEASURE(); para análises por cliente individual ou forma de pagamento, consulte fct_pedidos com dim_clientes.
Perguntas sobre alçadas de desconto, políticas comerciais ou regras de devolução devem consultar os documentos do volume politicas_comerciais e citar o arquivo fonte.
```

---

## 8. Exemplos SQL de Referência (`example_question_sqls`)

### 1. Qual foi o faturamento líquido mensal por canal no primeiro trimestre de 2025?
```sql
SELECT fct_pedidos.competencia_faturamento, fct_pedidos.canal_venda, SUM(fct_pedidos.valor_liquido) AS receita_liquida FROM analytics_dev.sales_gold.fct_pedidos AS fct_pedidos WHERE fct_pedidos.competencia_faturamento BETWEEN '2025-01' AND '2025-03' AND fct_pedidos.status_pedido = 'Faturado' GROUP BY fct_pedidos.competencia_faturamento, fct_pedidos.canal_venda ORDER BY fct_pedidos.competencia_faturamento, receita_liquida DESC
```
### 2. Como consultar os KPIs oficiais de receita líquida e ticket médio na Metric View por região?
```sql
SELECT regiao, MEASURE(receita_liquida_total) AS receita_oficial, MEASURE(ticket_medio) AS ticket_medio FROM analytics_dev.sales_gold.mv_kpis_comerciais WHERE competencia_faturamento = '2025-12' GROUP BY ALL ORDER BY receita_oficial DESC
```
### 3. Qual o ranking de segmentos de clientes por receita faturada em 2025?
```sql
SELECT dim_clientes.segmento, SUM(fct_pedidos.valor_liquido) AS receita_liquida, COUNT(DISTINCT fct_pedidos.id_cliente) AS clientes_ativos FROM analytics_dev.sales_gold.fct_pedidos AS fct_pedidos JOIN analytics_dev.sales_gold.dim_clientes AS dim_clientes ON fct_pedidos.id_cliente = dim_clientes.id_cliente WHERE LEFT(fct_pedidos.competencia_faturamento, 4) = '2025' AND fct_pedidos.status_pedido = 'Faturado' GROUP BY dim_clientes.segmento ORDER BY receita_liquida DESC
```
