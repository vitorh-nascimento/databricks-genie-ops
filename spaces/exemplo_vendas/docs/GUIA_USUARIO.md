# Guia do Usuário — Comercial & Receita Corporativa AI-BI

> **Público-Alvo:** Diretoria Comercial, RevOps, Analistas de BI e Executivos de Contas
> **Atualizado em:** 2026-11-23 11:14 UTC

---

## 1. O que este Assistente (Genie) consegue responder?

Genie Space curado para análise comercial corporativa, receita líquida, descontos, desempenho por canal/região, carteira de clientes B2B/B2C e políticas comerciais (Agent Mode).

### Domínios Suportados
- **Pedidos & Faturamento**
- **Carteira de Clientes**
- **KPIs Comerciais Governados**
- **Políticas Comerciais & Descontos**

### Documentos & Políticas Integradas (Agent Mode)
Este assistente também consulta documentos oficiais indexados em Unity Catalog Volumes:
- Manual de política comercial, alçadas de aprovação de desconto, regras de devolução e SLA de faturamento (PDF/MD). Consultar via Agent Mode e citar o arquivo fonte.

---

## 2. Exemplos de Perguntas Prontas para Testar

1. *"Qual foi a receita líquida faturada por região em 2026-01?"*
2. *"Quais são os 10 maiores clientes Enterprise por faturamento no último trimestre?"*
3. *"Qual a taxa de cancelamento por canal de venda em 2026?"*
4. *"Qual o ticket médio oficial por canal na Metric View de KPIs comerciais?"*
5. *"Qual é a alçada de aprovação necessária para descontos acima de 15% segundo a política comercial?"*

---

## 3. Vocabulário e Termos Reconhecidos

Você pode usar sinônimos naturais de negócio nas suas perguntas:

| Termo / Coluna | Sinônimos Aceitos | Significado |
| :--- | :--- | :--- |
| `id_cliente` (fct_pedidos) | — | Chave estrangeira do cliente para junção com dim_clientes. |
| `data_pedido` (fct_pedidos) | data da compra, data da venda | Data cronológica de criação do pedido pelo cliente no formato YYYY-MM-DD. |
| `competencia_faturamento` (fct_pedidos) | mês de faturamento, competência, período contábil | Mês de competência contábil do faturamento no formato YYYY-MM. Utilize sempre esta coluna para fechamento mensal de receita. |
| `status_pedido` (fct_pedidos) | status, situação do pedido | Situação operacional do pedido (Faturado, Cancelado, Pendente, Devolvido). |
| `canal_venda` (fct_pedidos) | canal, origem da venda | Canal comercial de origem da venda (E-commerce, Inside Sales, Marketplace, Parceiros). |
| `regiao` (fct_pedidos) | região comercial, praça | Macrorregião geográfica de atendimento comercial (Sudeste, Sul, Nordeste, Centro-Oeste, Norte). |
| `forma_pagamento` (fct_pedidos) | meio de pagamento, pagamento | Meio de pagamento utilizado no pedido (Pix, Cartão Corporativo, Boleto, Transferência). |
| `valor_bruto` (fct_pedidos) | — | Valor bruto do pedido antes de descontos em Reais (BRL). |
| `valor_desconto` (fct_pedidos) | — | Valor total de desconto concedido no pedido em Reais (BRL). |
| `valor_liquido` (fct_pedidos) | receita líquida, faturamento líquido, net revenue | Receita líquida faturada do pedido (valor_bruto menos valor_desconto) em Reais (BRL). |
| `id_cliente` (dim_clientes) | — | Identificador único do cliente (chave primária de dim_clientes). |
| `nome_cliente` (dim_clientes) | cliente, conta | Razão social ou nome fantasia do cliente. |
| `segmento` (dim_clientes) | segmento de cliente, carteira | Segmento de atuação do cliente (Enterprise, Mid-Market, SMB, Varejo). |
| `porte_empresa` (dim_clientes) | porte | Porte empresarial classificado por faixa de faturamento (Grande, Médio, Pequeno). |
| `uf` (dim_clientes) | estado | Sigla da unidade federativa (estado) da sede do cliente (ex. SP, RJ, MG, RS). |
| `data_cadastro` (dim_clientes) | — | Data de aquisição/cadastro inicial do cliente (YYYY-MM-DD). |
| `competencia_faturamento` (mv_kpis_comerciais) | — | Mês de competência contábil (YYYY-MM). |
| `regiao` (mv_kpis_comerciais) | — | Macrorregião comercial. |
| `canal_venda` (mv_kpis_comerciais) | — | Canal comercial de vendas. |
| `receita_liquida_total` (mv_kpis_comerciais) | faturamento oficial, receita oficial | Medida governada de receita líquida de pedidos faturados. |
| `ticket_medio` (mv_kpis_comerciais) | — | Medida governada de ticket médio por pedido faturado. |
| `taxa_desconto_pct` (mv_kpis_comerciais) | — | Percentual médio de desconto concedido sobre o valor bruto. |

---

## 4. Boas Práticas para Fazer Perguntas

1. **Informe o período desejado** (ex.: *"em março de 2026"*, *"no último trimestre"*) para evitar ambiguidade de datas.
2. **Especifique o recorte** (ex.: por região, canal de venda ou segmento de cliente) quando quiser comparações.
3. **Faça perguntas de acompanhamento** na mesma conversa para aprofundar um resultado (ex.: *"Agora quebre esse total por canal de venda"*).
4. **Dê feedback (👍/👎):** respostas marcadas negativamente são coletadas pelo time de dados via `genieops harvest-feedback` para evoluir continuamente a curadoria.

---

## 5. Limitações de Escopo

- Este Genie Space responde **exclusivamente** sobre as fontes governadas listadas na especificação técnica.
- Perguntas fora do domínio deste espaço devem ser direcionadas ao Genie Space correspondente ou ao time responsável (Data & Analytics — Squad Comercial).