# Databricks GenieOps — Regras e Governança do Repositório

Este repositório implementa o **Databricks GenieOps**, um framework reutilizável de **Genie-as-Code** para criar, documentar, auditar, testar, diagnosticar, monitorar e promover **Databricks Genie Spaces / Genie Agents** em múltiplos workspaces e ambientes (`dev` / `qa` / `prod`).

## Arquitetura & Stack
- **Backend / CLI (`genieops/`):** Python 3.12+, **Typer + Rich**, **Pydantic v2**, **PyYAML**, **Jinja2**, **SQLite WAL** (`.genieops/history.db`), **sqlglot** (AST profiling), **httpx** (SSE Agent Mode & LLM Judge), **FastAPI + Uvicorn** (Painel Web Local).
- **Frontend (`web/`):** React + TypeScript + Vite + Tailwind CSS (Painel Web Local servido via `genieops serve`).
- **Spaces declarativos (`spaces/<nome>/`):** 4 arquivos YAML (`space.yaml`, `sources.yaml`, `instructions.yaml`, `benchmarks.yaml`) compilados de forma determinística (UUID5 + ordenação estável) para o payload oficial `serialized_space` v2.
- **Qualidade:** `pytest`, `ruff`, CI em `.github/workflows/genie_ci.yml`.

## Regras Inegociáveis
1. **Zero segredos ou dados pessoais hardcoded:**
   - Nunca commitar tokens, chaves de API, e-mails pessoais, hostnames internos reais ou senhas.
   - Autenticação Databricks exclusivamente via perfis do Databricks CLI (`--profile`, `env/*.yaml`) ou variáveis de ambiente documentadas em `.env.example`.
2. **SQL estritamente Read-Only em profiling, linting e validação:**
   - Toda consulta de profiling, `EXPLAIN`, comparação de Result Sets, `system.query.history` e `system.access.audit` DEVE passar por `genieops.databricks_client.assert_read_only_sql`.
   - Apenas o módulo explícito `uc_export.py` (com opt-in explícito `--execute`) pode emitir DDL/DML restrito exclusivamente às tabelas `genie_opt_*` no `catalog.schema` aprovado pelo usuário.
3. **Conformidade estrita com Databricks Genie Agents (`serialized_space` v2):**
   - IDs 32-hex únicos e determinísticos (UUID5), arrays ordenados (incluindo `instructions.sql_functions` ordenado por `(id, identifier)`), `benchmarks` no nível raiz, `text_instructions <= 1` item compilado, zero colunas nuas em `join_specs`/`sql_snippets`, zero Benchmark Leakage entre `example_question_sqls` e `benchmarks.yaml` (incluindo `paraphrases`).
   - `update-space` é *full replacement*: nunca fazer deploy sem backup prévio automático em `.genieops/backups/<space>/<env>/`.
   - Artefatos de `curation_kit.py` (`uc-comments`, `seed-star-schema`) geram scripts SQL/PySpark revisáveis offline sem mutar diretamente o catálogo de produção.
4. **Hierarquia oficial de correção (menor superfície estruturada primeiro):**
   - Ordem obrigatória no diagnóstico e curadoria:
     1. Escopo e descrições de fontes (`sources.yaml`)
     2. `column_configs` (descrições, sinônimos, `exclude: true`)
     3. `enable_entity_matching` e `enable_format_assistance` seletivos
     4. Metadados/medidas governadas de Metric View (`MEASURE()`)
     5. `join_specs` validados por PK/FK e grão
     6. `sql_snippets` reutilizáveis (`measures`, `filters`, `expressions`)
     7. `example_question_sqls` representativos (sem leakage)
     8. `text_instructions` globais curtas (último recurso — nunca regra hardcoded de valor/tabela)
   - `diagnose` apenas analisa e propõe plano; nunca auto-muta um Genie Space sem aprovação explícita.

## Portão de Qualidade Obrigatório (Antes de Concluir Qualquer Tarefa)
Antes de encerrar qualquer alteração neste repositório, execute e valide:
1. `.venv\Scripts\pytest.exe -v` — 100% dos testes passando.
2. `.venv\Scripts\ruff.exe check genieops tests` — 0 erros.
3. Se `web/` foi alterado: `npm.cmd run build` dentro de `web/` com sucesso (0 erros de TypeScript/Vite).
4. Commit semântico no Git (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`) após todas as validações passarem.
