# Relatório Executivo de Qualidade — Comercial & Receita Corporativa AI-BI

**Space:** `exemplo_vendas` | **Responsável:** Data & Analytics — Squad Comercial | **Gerado em:** 2026-11-20 17:55 UTC
**Status de Prontidão para Produção:** **APROVADO PARA PRODUÇÃO**

---

## 1. Resumo Executivo

| Indicador | Valor |
| :--- | :--- |
| **Health Score (Linter)** | **99/100** (Erros: 0 / Avisos: 0 / Infos: 1) |
| **Fontes Governadas** | 2 tabela(s), 1 Metric View(s), 1 Volume(s) |
| **Cobertura de Benchmark** | 22 caso(s) cadastrados |
| **Última Assertividade (offline)** | **100.0%** (22/22 aprovados) |
| **Latência (Média / P50 / P95)** | 0.0ms / 0.0ms / 0.0ms |
| **Hash da Configuração** | `f637cb7fcbab` (`run_92ff3b390f`) |


---

## 2. Auditoria de Saúde (Genie Health Check)

| Severidade | Código | Superfície | Descrição |
| :---: | :---: | :--- | :--- |
| **INFO** | `BMK001` | `benchmarks.yaml` | Suíte de benchmark com 22 itens válidos (recomendação oficial Databricks para produção: >= 30). |

---

## 3. Histórico de Execuções de Benchmark

| Run ID | Data (UTC) | Ambiente | Modo | Assertividade | PASS / FAIL / REVIEW | P50 (ms) | P95 (ms) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `run_92ff3b390f` | 2026-11-20T17:55:40Z | `dev` | `offline` | **100.0%** | 22 / 0 / 0 | 0.0 | 0.0 |

---

## 4. Matriz Detalhada de Testes (Última Rodada)

| ID | Domínio | Dificuldade | Modo | Pergunta | Status | Latência (ms) |
| :--- | :--- | :---: | :---: | :--- | :---: | :---: |
| `bmk_01` | Faturamento | easy | chat | Qual foi a receita líquida total de pedidos faturados em janeiro de 2026? | **GOOD** | 0.0 |
| `bmk_02` | Descontos | easy | chat | Qual o total de descontos concedidos em fevereiro de 2026? | **GOOD** | 0.0 |
| `bmk_03` | Geografia | easy | chat | Qual a receita líquida faturada por região em março de 2026? | **GOOD** | 0.0 |
| `bmk_04` | Operações | easy | chat | Quantos pedidos foram cancelados por canal de venda em 2026-01? | **GOOD** | 0.0 |
| `bmk_05` | Pagamentos | easy | chat | Qual a distribuição da receita líquida por forma de pagamento em 2026-02? | **GOOD** | 0.0 |
| `bmk_06` | Faturamento | medium | chat | Qual a evolução mensal da receita líquida faturada ao longo de 2026? | **GOOD** | 0.0 |
| `bmk_07` | Clientes | medium | chat | Quais os 5 clientes com maior receita líquida faturada em 2026? | **GOOD** | 0.0 |
| `bmk_08` | Clientes | medium | chat | Qual foi o faturamento de clientes do segmento Enterprise na região Sudeste em 2026-01? | **GOOD** | 0.0 |
| `bmk_09` | Geografia | medium | chat | Qual a receita líquida por UF para clientes de porte Grande em 2026? | **GOOD** | 0.0 |
| `bmk_10` | Operações | hard | chat | Qual a taxa de cancelamento percentual por região em 2026-01? | **GOOD** | 0.0 |
| `bmk_11` | Descontos | hard | chat | Qual o percentual médio de desconto concedido por canal de venda em 2026-03? | **GOOD** | 0.0 |
| `bmk_12` | Clientes | medium | chat | Quantos clientes únicos compraram no canal E-commerce em cada mês de 2026? | **GOOD** | 0.0 |
| `bmk_13` | Pagamentos | easy | chat | Qual o ticket médio dos pedidos pagos via Pix em fevereiro de 2026? | **GOOD** | 0.0 |
| `bmk_14` | KPIs Governados | hard | chat | Quais canais de venda tiveram receita líquida oficial acima de 500 mil em 2026-01 segundo a Metric View? | **GOOD** | 0.0 |
| `bmk_15` | KPIs Governados | medium | chat | Qual o ticket médio e a taxa de desconto oficial por região em 2026-02 na Metric View? | **GOOD** | 0.0 |
| `bmk_16` | Clientes | hard | chat | Qual a participação percentual de cada segmento na receita líquida total de 2026? | **GOOD** | 0.0 |
| `bmk_17` | Clientes | easy | chat | Quantos novos clientes foram cadastrados por segmento em 2026? | **GOOD** | 0.0 |
| `bmk_18` | Faturamento | medium | chat | Qual a diferença entre valor bruto e valor líquido por status de pedido em 2026-01? | **GOOD** | 0.0 |
| `bmk_19` | Faturamento | hard | chat | Qual foi o crescimento percentual de receita líquida de 2026-02 em relação a 2026-01? | **GOOD** | 0.0 |
| `bmk_20` | Operações | medium | chat | Quais pedidos devolvidos em 2026 superaram 10 mil reais de valor líquido? | **GOOD** | 0.0 |
| `bmk_21` | Políticas Comerciais | medium | agent | Qual é a alçada de aprovação exigida para descontos comerciais acima de 15% e qual documento define essa regra? | **GOOD** | 0.0 |
| `bmk_22` | Políticas Comerciais | hard | agent | Compare os pedidos devolvidos de 2026-01 com o prazo máximo de devolução previsto na política comercial. | **GOOD** | 0.0 |
