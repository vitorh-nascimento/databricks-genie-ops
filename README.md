# Databricks GenieOps — Framework Genie-as-Code

Toolkit reutilizável de **Genie-as-Code** para criar, curar, auditar, testar, diagnosticar, documentar e promover **Databricks Genie Spaces / Genie Agents** em múltiplos workspaces e ambientes (`dev` / `qa` / `prod`), tanto localmente no terminal quanto em pipelines CI/CD (GitHub Actions, Azure DevOps ou Databricks Asset Bundles).

---

## Arquitetura & Princípios

- **Declarativo & Determinístico:** cada Genie Space vive em `spaces/<nome>/` em 4 arquivos YAML legíveis (`space.yaml`, `sources.yaml`, `instructions.yaml`, `benchmarks.yaml`) compilados para o formato oficial **`serialized_space` v2** com ordenação estável e IDs 32-hex determinísticos (UUID5) — zero ruído em diffs do Git.
- **Somente Leitura no Profiling & Validação:** todas as consultas de `profile`, `lint --validate-sql` e comparação de Result Sets passam por guarda estrita de SQL read-only (`SELECT`/`WITH`/`SHOW`/`DESCRIBE`/`EXPLAIN`).
- **Deploy Seguro com Rollback:** antes de executar `update-space` (full replacement), salva automaticamente o snapshot remoto em `.genieops/backups/<space>/<env>/`.
- **Zero Segredos no Repositório:** autenticação exclusivamente via perfis do Databricks CLI (`--profile` / `env/*.yaml`) ou variáveis de ambiente (`.env.example`).

```text
databricks-genie-ops/
├── genieops/                 # CLI Typer, modelos Pydantic, compilador v2, linter, benchmark, docs
├── spaces/                   # Definições declarativas versionadas por Genie Space
│   └── exemplo_vendas/       # Template corporativo pronto para testar imediatamente
├── env/                      # Defaults globais por ambiente (dev.yaml, qa.yaml, prod.yaml)
├── templates/                # Templates Jinja2 (SPEC_TECNICA, RELATORIO_EXECUTIVO MD/HTML, GUIA_USUARIO)
├── tests/                    # Suíte pytest com mocks completos do Databricks CLI
└── .github/workflows/        # Pipeline CI pronta (pytest + lint + benchmark offline + docs)
```

---

## Instalação Rápida

Pré-requisitos: **Python 3.11+** e (para operações remotas no Databricks) **Databricks CLI `>= v1.0.0`** autenticado via `databricks auth login --profile <perfil>`.

```powershell
# Clonar e criar ambiente virtual
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"

# Validar instalação e rodar os testes unitários
genieops version
pytest
```

### Teste Imediato com o Template `exemplo_vendas` (Sem Precisar de Workspace)

```powershell
genieops list
genieops lint exemplo_vendas --strict
genieops benchmark exemplo_vendas --env dev --mode offline
genieops docs exemplo_vendas
genieops compile exemplo_vendas --env prod --output .genieops/staging/exemplo_vendas_prod.json
```

---

## Fluxo de Trabalho Recomendado (Ciclo de Vida GenieOps)

```text
init / pull  ──▶  profile  ──▶  lint  ──▶  diff / deploy  ──▶  benchmark  ──▶  diagnose  ──▶  docs  ──▶  migrate
```

| Etapa | Comando | Finalidade |
| :--- | :--- | :--- |
| **1. Criar / Importar** | `genieops init <nome>` ou `genieops pull <space_id> --profile <p>` | Cria scaffold declarativo ou importa um Genie existente do Databricks para YAML. |
| **2. Profiling (Read-Only + AST)** | `genieops profile <nome> --env dev [--query-history]` | Analisa metadados/cardinalidade e faz parsing AST (`sqlglot`) em `system.query.history` sugerindo `entity_matching`, `exclude`, joins, filtros e medidas. |
| **3. Genie Health Check** | `genieops lint <nome> [--validate-sql --env dev] [--strict]` | Audita boas práticas (fontes, `column_configs`, qualificação SQL, benchmark leakage, `text_instructions`, `EXPLAIN`). |
| **4. Diff & Deploy Seguro** | `genieops diff <nome> --env dev` / `genieops deploy <nome> --env dev` | Compara estado local vs remoto e aplica `create-space`/`update-space` com backup automático de rollback. |
| **5. Benchmark & Regressão** | `genieops benchmark <nome> --env dev --mode <offline\|live\|eval-run\|agent>` | Avalia assertividade (Result Sets + Streaming SSE Agent Mode + LLM-as-a-Judge plugável), latência P50/P95 e salva regressão em SQLite (`history.db`). |
| **6. Diagnóstico** | `genieops diagnose <nome> [--run-id <id>]` | Classifica causa raiz das falhas e propõe plano de correção seguindo a hierarquia oficial Databricks (sem auto-mutar). |
| **7. Coleta de Feedback** | `genieops harvest-feedback <nome> --env prod [--include-audit]` | Extrai falhas/feedback negativo (API + `system.access.audit`) com deduplicação semântica para `benchmarks_draft.yaml`. |
| **8. Documentação** | `genieops docs <nome>` | Gera `SPEC_TECNICA.md`, `RELATORIO_EXECUTIVO.md`, `relatorio_executivo.html` e `GUIA_USUARIO.md`. |
| **9. Promoção Multi-Env** | `genieops migrate <nome> --from dev --to prod [--deploy]` | Remapeia `catalog`, `schema` e `/Volumes/...` em todas as superfícies e promove entre workspaces. |
| **10. Exportação Delta (UC)** | `genieops export-delta <nome> --catalog <cat> --schema <sch> [--execute]` | Exporta `history.db` para as tabelas Delta oficiais Databricks (`genie_opt_runs`, `config_versions`, `eval_results`, `repair_analysis` ou `genie_opt_events`). |
| **11. Painel Web Local** | `genieops serve [--port 8765]` | Abre o dashboard local **FastAPI + React/Vite/Tailwind** com Health Check, gráficos de regressão, diagnóstico, Agent Mode SSE e preview Delta. |

---

## Roadmap em Fases

- **Fase 1 (Concluída):** CLI modular completa (`genieops`), compilador determinístico `serialized_space` v2 + parser reverso (`pull`), `diff`/`deploy` com backup automático, migrador multi-ambiente, Linter estático + `EXPLAIN`, motor de Benchmark (`offline`, `live` com equivalência de Result Sets, wrapper `eval-run`), histórico SQLite com regressão e P50/P95, `diagnose` por hierarquia oficial, `profile` e `harvest-feedback` read-only, geração de docs MD/HTML, CI/CD GitHub Actions e suíte `pytest`.
- **Fase 2 (Concluída):**
  - **AST Profiling (`sqlglot`):** análise sintática sobre `system.query.history` para sugerir `join_specs`, filtros recorrentes e medidas/agregações.
  - **Agent Mode SSE + LLM-as-a-Judge plugável:** streaming SSE de `/api/2.0/genie/agents/{space_id}/responses` (`STANDARD` / `FLASH`) com avaliadores `heuristic`, `databricks` (Foundation Model API) e `openai` (OpenAI-compatible).
  - **Exportação Delta no Unity Catalog:** geração de DDL + `MERGE INTO` idempotente alinhado ao schema oficial Databricks (`four_tables` e `events`) com guarda allowlist `genie_opt_*`.
  - **Harvester Semântico + Audit Log:** integração read-only com `system.access.audit` e deduplicação semântica de reformulações.
  - **Painel Web Local (`genieops serve`):** API FastAPI + interface React/TypeScript/Vite/Tailwind em `web/`.

---

## Checklist de Prontidão para Produção

- [ ] `genieops lint <space> --validate-sql --env prod --strict` com **0 erros** e **Health Score >= 85/100**.
- [ ] Fontes focadas (<= 5 tabelas/Metric Views) com `column_configs` preenchidos e colunas técnicas ocultadas (`exclude: true`).
- [ ] Zero colunas nuas em `join_specs` e `sql_snippets`; zero Benchmark Leakage entre `example_question_sqls` e `benchmarks.yaml`.
- [ ] Suíte de benchmark com **>= 20–30 perguntas** variadas (easy/medium/hard) e assertividade **>= 90%** em modo `live` ou `eval-run`.
- [ ] Nenhuma regressão (`regressed = 0`) em relação à última versão homologada no `history.db`.
- [ ] Volumes de documentos criados e indexados no ambiente de destino (para Agents com documentos).
- [ ] Documentação atualizada (`SPEC_TECNICA.md`, `RELATORIO_EXECUTIVO.md/.html`, `GUIA_USUARIO.md`) revisada em Pull Request.
