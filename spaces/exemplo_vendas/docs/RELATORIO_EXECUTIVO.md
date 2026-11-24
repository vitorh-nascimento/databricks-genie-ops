# Relatório Executivo de Qualidade — Comercial & Receita Corporativa AI-BI

**Space:** `exemplo_vendas` | **Responsável:** Data & Analytics — Squad Comercial | **Gerado em:** 2026-11-23 11:14 UTC
**Status de Prontidão para Produção:** **EM HOMOLOGAÇÃO — Apenas Validação Offline (rode live/eval-run/agent)**

---

## 1. Resumo Executivo

| Indicador | Valor |
| :--- | :--- |
| **Health Score (Linter)** | **100/100** (Erros: 0 / Avisos: 0 / Infos: 0) |
| **Fontes Governadas** | 2 tabela(s), 1 Metric View(s), 1 Volume(s), 3 SQL Function(s) |
| **Cobertura de Benchmark** | 32 caso(s) canônicos (+ 64 paráfrases = 96 variações) |
| **Última Assertividade (offline)** | **100.0%** (96/96 aprovados) |
| **Latência (Média / P50 / P95)** | 0.0ms / 0.0ms / 0.0ms |
| **Hash da Configuração** | `0d0b00588e12` (`run_aabd699984`) |

### Evolução vs Rodada Anterior (`run_9027101977` → `run_aabd699984`)
- **Score:** 100.0% → **100.0%** (+0.00 pp)
- **Corrigidos (`BAD → GOOD`):** 0
- **Regressões (`GOOD → BAD`):** 0
- **Inalterados:** 22

---

## 2. Auditoria de Saúde (Genie Health Check)

Nenhum problema detectado pelo Linter. Todas as regras estáticas de curadoria passaram com sucesso.

---

## 3. Evolução da Acurácia por Rodada de Curadoria

| Rodada / Etapa | Run ID | Ambiente / Modo | Assertividade | Delta (pp) | PASS / FAIL / REVIEW | P50 (ms) | P95 (ms) | Config Hash |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Rodada 0** | `run_92ff3b390f` | `dev` / `offline` | **100.0%** | baseline | 22 / 0 / 0 | 0.0 | 0.0 | `f637cb7f` |
| **Rodada 1** | `run_9027101977` | `dev` / `offline` | **100.0%** | +0.00 pp | 22 / 0 / 0 | 0.0 | 0.0 | `f637cb7f` |
| **Rodada 4 - Curadoria Completa** | `run_aabd699984` | `dev` / `offline` | **100.0%** | +0.00 pp | 96 / 0 / 0 | 0.0 | 0.0 | `0d0b0058` |

---

## 4. Matriz Detalhada de Testes (Última Rodada)

| ID | Domínio | Dificuldade | Modo | Pergunta | Status | Latência (ms) |
| :--- | :--- | :---: | :---: | :--- | :---: | :---: |
| `bmk_01` | Faturamento | easy | chat | Qual foi a receita líquida total de pedidos faturados em janeiro de 2026? | **GOOD** | 0.0 |
| `bmk_01__p1` | Faturamento | easy | chat | Quanto faturamos líquido em 2026-01 considerando apenas pedidos confirmados? | **GOOD** | 0.0 |
| `bmk_01__p2` | Faturamento | easy | chat | Qual o total de receita líquida realizada em janeiro de 2026? | **GOOD** | 0.0 |
| `bmk_02` | Descontos | easy | chat | Qual o total de descontos concedidos em fevereiro de 2026? | **GOOD** | 0.0 |
| `bmk_02__p1` | Descontos | easy | chat | Quanto demos de desconto em pedidos faturados na competência 2026-02? | **GOOD** | 0.0 |
| `bmk_02__p2` | Descontos | easy | chat | Qual foi o montante total de abatimentos em fevereiro de 2026? | **GOOD** | 0.0 |
| `bmk_03` | Geografia | easy | chat | Qual a receita líquida faturada por região em março de 2026? | **GOOD** | 0.0 |
| `bmk_03__p1` | Geografia | easy | chat | Mostre o faturamento líquido quebrado por macrorregião em 2026-03. | **GOOD** | 0.0 |
| `bmk_03__p2` | Geografia | easy | chat | Quanto cada praça comercial faturou líquido em março de 2026? | **GOOD** | 0.0 |
| `bmk_04` | Operações | easy | chat | Quantos pedidos foram cancelados por canal de venda em 2026-01? | **GOOD** | 0.0 |
| `bmk_04__p1` | Operações | easy | chat | Qual o volume de cancelamentos por origem da venda em janeiro de 2026? | **GOOD** | 0.0 |
| `bmk_04__p2` | Operações | easy | chat | Liste a quantidade de pedidos com status Cancelado por canal em 2026-01. | **GOOD** | 0.0 |
| `bmk_05` | Pagamentos | easy | chat | Qual a distribuição da receita líquida por forma de pagamento em 2026-02? | **GOOD** | 0.0 |
| `bmk_05__p1` | Pagamentos | easy | chat | Como ficou o faturamento líquido por meio de pagamento em fevereiro de 2026? | **GOOD** | 0.0 |
| `bmk_05__p2` | Pagamentos | easy | chat | Agrupe a receita realizada em 2026-02 por forma de pagamento. | **GOOD** | 0.0 |
| `bmk_06` | Faturamento | medium | chat | Qual a evolução mensal da receita líquida faturada ao longo de 2026? | **GOOD** | 0.0 |
| `bmk_06__p1` | Faturamento | medium | chat | Mostre a série histórica mês a mês do faturamento líquido em 2026. | **GOOD** | 0.0 |
| `bmk_06__p2` | Faturamento | medium | chat | Como a receita confirmada variou por competência durante o ano de 2026? | **GOOD** | 0.0 |
| `bmk_07` | Clientes | medium | chat | Quais os 5 clientes com maior receita líquida faturada em 2026? | **GOOD** | 0.0 |
| `bmk_07__p1` | Clientes | medium | chat | Quem são os top 5 clientes por faturamento líquido realizado em 2026? | **GOOD** | 0.0 |
| `bmk_07__p2` | Clientes | medium | chat | Liste as cinco maiores contas em receita líquida confirmada no ano de 2026. | **GOOD** | 0.0 |
| `bmk_08` | Clientes | medium | chat | Qual foi o faturamento de clientes do segmento Enterprise na região Sudeste em 2026-01? | **GOOD** | 0.0 |
| `bmk_08__p1` | Clientes | medium | chat | Quanto faturamos com grandes contas Enterprise no Sudeste em janeiro de 2026? | **GOOD** | 0.0 |
| `bmk_08__p2` | Clientes | medium | chat | Qual a receita líquida faturada da carteira Enterprise na região Sudeste em 2026-01? | **GOOD** | 0.0 |
| `bmk_09` | Geografia | medium | chat | Qual a receita líquida por UF para clientes de porte Grande em 2026? | **GOOD** | 0.0 |
| `bmk_09__p1` | Geografia | medium | chat | Mostre o faturamento líquido por estado considerando somente empresas de grande porte em 2026. | **GOOD** | 0.0 |
| `bmk_09__p2` | Geografia | medium | chat | Quanto clientes de porte Grande faturaram em cada UF ao longo de 2026? | **GOOD** | 0.0 |
| `bmk_10` | Operações | hard | chat | Qual a taxa de cancelamento percentual por região em 2026-01? | **GOOD** | 0.0 |
| `bmk_10__p1` | Operações | hard | chat | Qual o percentual de pedidos cancelados em cada macrorregião em janeiro de 2026? | **GOOD** | 0.0 |
| `bmk_10__p2` | Operações | hard | chat | Calcule o churn de pedidos por região na competência 2026-01. | **GOOD** | 0.0 |
| `bmk_11` | Descontos | hard | chat | Qual o percentual médio de desconto concedido por canal de venda em 2026-03? | **GOOD** | 0.0 |
| `bmk_11__p1` | Descontos | hard | chat | Qual foi a taxa efetiva de desconto por canal comercial em março de 2026? | **GOOD** | 0.0 |
| `bmk_11__p2` | Descontos | hard | chat | Calcule o desconto percentual sobre o valor bruto por origem da venda em 2026-03. | **GOOD** | 0.0 |
| `bmk_12` | Clientes | medium | chat | Quantos clientes únicos compraram no canal E-commerce em cada mês de 2026? | **GOOD** | 0.0 |
| `bmk_12__p1` | Clientes | medium | chat | Qual a base mensal de clientes distintos ativos no E-commerce em 2026? | **GOOD** | 0.0 |
| `bmk_12__p2` | Clientes | medium | chat | Conte quantos clientes diferentes faturaram pelo E-commerce por competência em 2026. | **GOOD** | 0.0 |
| `bmk_13` | Pagamentos | easy | chat | Qual o ticket médio dos pedidos pagos via Pix em fevereiro de 2026? | **GOOD** | 0.0 |
| `bmk_13__p1` | Pagamentos | easy | chat | Qual foi o valor líquido médio por pedido faturado no Pix em 2026-02? | **GOOD** | 0.0 |
| `bmk_13__p2` | Pagamentos | easy | chat | Calcule o ticket médio das vendas pagas com Pix em fevereiro de 2026. | **GOOD** | 0.0 |
| `bmk_14` | KPIs Governados | hard | chat | Quais canais de venda tiveram receita líquida oficial acima de 500 mil em 2026-01 segundo a Metric View? | **GOOD** | 0.0 |
| `bmk_14__p1` | KPIs Governados | hard | chat | Na Metric View de KPIs comerciais, quais canais superaram R$ 500 mil de receita oficial em 2026-01? | **GOOD** | 0.0 |
| `bmk_14__p2` | KPIs Governados | hard | chat | Filtre os canais com faturamento oficial maior que 500.000 em janeiro de 2026 na mv_kpis_comerciais. | **GOOD** | 0.0 |
| `bmk_15` | KPIs Governados | medium | chat | Qual o ticket médio e a taxa de desconto oficial por região em 2026-02 na Metric View? | **GOOD** | 0.0 |
| `bmk_15__p1` | KPIs Governados | medium | chat | Consulte na mv_kpis_comerciais o ticket médio e o percentual de desconto oficial por região em fevereiro de 2026. | **GOOD** | 0.0 |
| `bmk_15__p2` | KPIs Governados | medium | chat | Mostre ticket_medio e taxa_desconto_pct governados por macrorregião na competência 2026-02. | **GOOD** | 0.0 |
| `bmk_16` | Clientes | hard | chat | Qual a participação percentual de cada segmento na receita líquida total de 2026? | **GOOD** | 0.0 |
| `bmk_16__p1` | Clientes | hard | chat | Qual o share de faturamento líquido por segmento de cliente no ano de 2026? | **GOOD** | 0.0 |
| `bmk_16__p2` | Clientes | hard | chat | Calcule quanto cada carteira representa percentualmente na receita realizada de 2026. | **GOOD** | 0.0 |
| `bmk_17` | Clientes | easy | chat | Quantos novos clientes foram cadastrados por segmento em 2026? | **GOOD** | 0.0 |
| `bmk_17__p1` | Clientes | easy | chat | Qual foi a aquisição de contas novas por segmento de cliente durante 2026? | **GOOD** | 0.0 |
| `bmk_17__p2` | Clientes | easy | chat | Conte quantos clientes entraram na base em 2026 quebrado por segmento. | **GOOD** | 0.0 |
| `bmk_18` | Faturamento | medium | chat | Qual a diferença entre valor bruto e valor líquido por status de pedido em 2026-01? | **GOOD** | 0.0 |
| `bmk_18__p1` | Faturamento | medium | chat | Compare total bruto, total líquido e diferença por situação do pedido em janeiro de 2026. | **GOOD** | 0.0 |
| `bmk_18__p2` | Faturamento | medium | chat | Mostre valor_bruto vs valor_liquido agrupados por status_pedido em 2026-01. | **GOOD** | 0.0 |
| `bmk_19` | Faturamento | hard | chat | Qual foi o crescimento percentual de receita líquida de 2026-02 em relação a 2026-01? | **GOOD** | 0.0 |
| `bmk_19__p1` | Faturamento | hard | chat | Qual a variação MoM percentual do faturamento líquido entre janeiro e fevereiro de 2026? | **GOOD** | 0.0 |
| `bmk_19__p2` | Faturamento | hard | chat | Quanto a receita confirmada cresceu ou caiu de 2026-01 para 2026-02 em percentual? | **GOOD** | 0.6 |
| `bmk_20` | Operações | medium | chat | Quais pedidos devolvidos em 2026 superaram 10 mil reais de valor líquido? | **GOOD** | 0.0 |
| `bmk_20__p1` | Operações | medium | chat | Liste as devoluções de 2026 com valor líquido acima de R$ 10.000. | **GOOD** | 0.0 |
| `bmk_20__p2` | Operações | medium | chat | Mostre pedidos com status Devolvido em 2026 cuja receita líquida passou de 10 mil. | **GOOD** | 0.0 |
| `bmk_21` | Políticas Comerciais | medium | agent | Qual é a alçada de aprovação exigida para descontos comerciais acima de 15% e qual documento define essa regra? | **GOOD** | 0.0 |
| `bmk_21__p1` | Políticas Comerciais | medium | agent | Quem precisa aprovar descontos superiores a 15% segundo o manual comercial e qual arquivo cita essa norma? | **GOOD** | 0.0 |
| `bmk_21__p2` | Políticas Comerciais | medium | agent | Qual a regra de governança para conceder mais de 15% de desconto conforme a política comercial? | **GOOD** | 0.0 |
| `bmk_22` | Políticas Comerciais | hard | agent | Compare os pedidos devolvidos de 2026-01 com o prazo máximo de devolução previsto na política comercial. | **GOOD** | 0.0 |
| `bmk_22__p1` | Políticas Comerciais | hard | agent | Cruze as devoluções de janeiro de 2026 na base de pedidos com o limite de dias permitido pela política comercial. | **GOOD** | 0.0 |
| `bmk_22__p2` | Políticas Comerciais | hard | agent | Analise os pedidos Devolvido em 2026-01 frente ao prazo oficial de devolução documentado no manual. | **GOOD** | 0.0 |
| `bmk_23` | Faturamento | hard | chat | Quantos pedidos tiveram data de compra diferente do mês de competência de faturamento em 2026? | **GOOD** | 0.0 |
| `bmk_23__p1` | Faturamento | hard | chat | Em 2026, quantos pedidos viraram o mês entre data_pedido e competencia_faturamento? | **GOOD** | 0.0 |
| `bmk_23__p2` | Faturamento | hard | chat | Conte os pedidos de 2026 onde o mês da data do pedido não coincide com o mês de faturamento. | **GOOD** | 0.0 |
| `bmk_24` | Descontos | medium | chat | Quantos pedidos faturados em 2026 receberam desconto superior a 15% sobre o valor bruto? | **GOOD** | 0.0 |
| `bmk_24__p1` | Descontos | medium | chat | Qual a quantidade de vendas confirmadas em 2026 com percentual de desconto acima de 15%? | **GOOD** | 0.0 |
| `bmk_24__p2` | Descontos | medium | chat | Conte os pedidos faturados no ano de 2026 que exigiram alçada por desconto > 15%. | **GOOD** | 0.0 |
| `bmk_25` | KPIs Governados | medium | chat | Qual a receita líquida por região e canal no primeiro trimestre de 2026 usando a função oficial fn_receita_liquida_periodo? | **GOOD** | 0.0 |
| `bmk_25__p1` | KPIs Governados | medium | chat | Consulte o trusted asset fn_receita_liquida_periodo entre 2026-01 e 2026-03. | **GOOD** | 0.0 |
| `bmk_25__p2` | KPIs Governados | medium | chat | Use a função governada de receita líquida por período para o Q1 de 2026. | **GOOD** | 0.0 |
| `bmk_26` | Operações | medium | chat | Qual a taxa de cancelamento por região em 2026-02 usando a função oficial fn_taxa_cancelamento_regiao? | **GOOD** | 0.0 |
| `bmk_26__p1` | Operações | medium | chat | Execute a função governada fn_taxa_cancelamento_regiao para fevereiro de 2026. | **GOOD** | 0.0 |
| `bmk_26__p2` | Operações | medium | chat | Traga o percentual oficial de cancelamento regional de 2026-02 pelo trusted asset. | **GOOD** | 0.0 |
| `bmk_27` | Clientes | medium | chat | Quais os 10 maiores clientes Enterprise em 2026 segundo a função oficial fn_top_clientes_segmento? | **GOOD** | 0.0 |
| `bmk_27__p1` | Clientes | medium | chat | Liste o top 10 Enterprise de 2026 utilizando o trusted asset fn_top_clientes_segmento. | **GOOD** | 0.0 |
| `bmk_27__p2` | Clientes | medium | chat | Consulte a função fn_top_clientes_segmento para o segmento Enterprise no ano de 2026. | **GOOD** | 0.0 |
| `bmk_28` | Faturamento | hard | chat | Qual a receita líquida total de pedidos faturados em 2026 excluindo clientes do segmento Interno? | **GOOD** | 0.0 |
| `bmk_28__p1` | Faturamento | hard | chat | Quanto faturamos em 2026 desconsiderando contas internas de teste? | **GOOD** | 0.0 |
| `bmk_28__p2` | Faturamento | hard | chat | Calcule o faturamento líquido realizado de 2026 sem o segmento Interno. | **GOOD** | 0.0 |
| `bmk_29` | Operações | easy | chat | Qual o valor total de pedidos ainda pendentes por região em março de 2026? | **GOOD** | 0.0 |
| `bmk_29__p1` | Operações | easy | chat | Quanto temos em backlog de pedidos com status Pendente por região em 2026-03? | **GOOD** | 0.0 |
| `bmk_29__p2` | Operações | easy | chat | Mostre a soma de valor líquido pendente por praça em março de 2026. | **GOOD** | 0.0 |
| `bmk_30` | Geografia | medium | chat | Quais UFs possuem maior ticket médio de pedidos faturados em 2026 entre clientes SMB? | **GOOD** | 0.0 |
| `bmk_30__p1` | Geografia | medium | chat | Qual o ranking de estados por ticket médio no segmento SMB durante 2026? | **GOOD** | 0.0 |
| `bmk_30__p2` | Geografia | medium | chat | Calcule a média de valor líquido por UF para a carteira SMB em 2026. | **GOOD** | 0.0 |
| `bmk_31` | Clientes | hard | chat | Qual a média de pedidos faturados por cliente ativo em cada segmento no ano de 2026? | **GOOD** | 0.0 |
| `bmk_31__p1` | Clientes | hard | chat | Qual a frequência média de compras por cliente distinto em cada segmento durante 2026? | **GOOD** | 0.0 |
| `bmk_31__p2` | Clientes | hard | chat | Divida o número de pedidos faturados pelo total de clientes únicos por segmento em 2026. | **GOOD** | 0.0 |
| `bmk_32` | KPIs Governados | medium | chat | Qual a receita líquida oficial consolidada por canal no primeiro trimestre de 2026 na Metric View? | **GOOD** | 0.0 |
| `bmk_32__p1` | KPIs Governados | medium | chat | Some a receita oficial por canal de venda de 2026-01 a 2026-03 consultando mv_kpis_comerciais. | **GOOD** | 0.0 |
| `bmk_32__p2` | KPIs Governados | medium | chat | Mostre MEASURE(receita_liquida_total) por canal no Q1 de 2026 pela Metric View. | **GOOD** | 0.0 |
