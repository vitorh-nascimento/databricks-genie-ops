# Playbook de Curadoria Progressiva — Genie Space (`exemplo_vendas`)

Este guia implementa de ponta a ponta o fluxo experimental de curadoria em camadas para medir objetivamente a evolução da acurácia no Unity Catalog (`analytics_dev.sales_gold`).

---

## Etapa 0 — Preparar Base Fictícia Star Schema & Governança no Unity Catalog

1. **Criar tabelas Delta com armadilhas de negócio:** execute `01_seed_star_schema.py` no Databricks (Serverless Notebook ou Job).
2. **Aplicar COMMENTs em tabelas e colunas no Unity Catalog:** execute `02_uc_comments.sql` (também regenerável para qualquer Space via `genieops uc-comments exemplo_vendas`).
3. **Registrar Trusted Assets (SQL Functions):** execute `03_trusted_sql_functions.sql` no SQL Warehouse.

---

## Rodadas Progressivas de Curadoria & Benchmark

Cada rodada aplica **uma camada adicional** de contexto, faz deploy versionado e registra a acurácia rotulada em `.genieops/history.db`:

### Rodada 0 — Baseline (Somente Tabelas)
- Mantenha `instructions.yaml` vazio (sem `text_instructions`, `example_question_sqls`, `sql_snippets` ou `sql_functions`).
```powershell
genieops deploy exemplo_vendas --env dev --skip-lint
genieops benchmark exemplo_vendas --env dev --mode live --expand-paraphrases --label "Rodada 0 - Só tabelas"
```

### Rodada 1 — + COMMENTs no UC & `column_configs` (Sinônimos + Entity Matching)
- Aplique `02_uc_comments.sql` no Unity Catalog e preencha `sources.yaml` (`description`, `synonyms`, `enable_entity_matching`, `exclude`).
```powershell
genieops deploy exemplo_vendas --env dev
genieops benchmark exemplo_vendas --env dev --mode live --expand-paraphrases --label "Rodada 1 - +UC Comments e Column Configs"
```

### Rodada 2 — + Instruções em Texto (`text_instructions`) + Joins & Snippets
- Adicione as regras globais concisas em `instructions.yaml` (`text_instructions`, `join_specs`, `sql_snippets`).
```powershell
genieops deploy exemplo_vendas --env dev
genieops benchmark exemplo_vendas --env dev --mode live --expand-paraphrases --label "Rodada 2 - +Text Instructions"
```

### Rodada 3 — + SQLs de Exemplo (`example_question_sqls`)
- Adicione exemplos representativos por padrão de consulta (o `genieops lint --strict` garante 0% de Benchmark Leakage).
```powershell
genieops lint exemplo_vendas --strict
genieops deploy exemplo_vendas --env dev
genieops benchmark exemplo_vendas --env dev --mode live --expand-paraphrases --label "Rodada 3 - +SQLs de Exemplo"
```

### Rodada 4 — + SQL Functions / Trusted Assets (`sql_functions`)
- Referencie as 3 UDFs governadas (`fn_receita_liquida_periodo`, `fn_taxa_cancelamento_regiao`, `fn_top_clientes_segmento`) em `instructions.yaml`.
```powershell
genieops lint exemplo_vendas --validate-sql --env dev --strict
genieops deploy exemplo_vendas --env dev
genieops benchmark exemplo_vendas --env dev --mode live --expand-paraphrases --label "Rodada 4 - +SQL Functions (Trusted Assets)"
```

---

## Etapa Final — Persistir Rodadas em Tabela Delta & Gerar Relatório de Evolução

1. **Registrar todas as rodadas em tabelas Delta no Unity Catalog (`genie_opt_runs`, `genie_opt_eval_results`, etc.):**
```powershell
# Preview SQL seguro (dry-run):
genieops export-delta exemplo_vendas --catalog analytics_dev --schema genieops_audit

# Executar no SQL Warehouse (opt-in explícito):
genieops export-delta exemplo_vendas --catalog analytics_dev --schema genieops_audit --execute
```

2. **Gerar documentação completa com a tabela de evolução da acurácia por rodada:**
```powershell
genieops docs exemplo_vendas
```
Os artefatos gerados (`RELATORIO_EXECUTIVO.md`, `relatorio_executivo.html`, `SPEC_TECNICA.md` e `GUIA_USUARIO.md`) incluem a **Tabela de Evolução da Acurácia por Rodada** com rótulo, delta (pp), taxa de acerto e latência P50/P95.
