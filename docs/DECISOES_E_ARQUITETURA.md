# Decisões de Negócio, Arquitetura e "Por Quês" (ADRs)

Este documento registra **por que** o **Databricks GenieOps** foi desenhado desta forma, quais problemas reais de negócio e engenharia ele resolve em ambientes corporativos Databricks, e os trade-offs adotados em cada pilar técnico.

---

## Contexto de Negócio: O Problema que Resolvemos

Times de Dados e Analytics adotam **Databricks Genie Spaces / Genie Agents** para democratizar consultas em linguagem natural sobre dados governados no Unity Catalog e documentos em UC Volumes. Porém, quando um Genie sai de uma PoC e vai para produção em múltiplos domínios e workspaces (`dev`, `qa`, `prod`), surgem 6 dores recorrentes:

1. **Curadoria "caixa-preta" via UI:** alterações feitas manualmente na interface não têm revisão em Pull Request, histórico legível de quem mudou o quê, nem rollback seguro (`update-space` substitui toda a configuração de uma vez).
2. **Regressões silenciosas:** ajustar uma instrução para corrigir a pergunta A frequentemente quebra silenciosamente as perguntas B e C que já funcionavam.
3. **Promoção manual e propensa a erro entre ambientes:** copiar manualmente tabelas, Metric Views, `/Volumes/...`, SQL snippets e exemplos de `dev` para `prod` gera inconsistências e retrabalho.
4. **Excesso de regras em texto livre (`text_instructions`):** equipes tendem a colar manuais gigantes e mapeamentos hardcoded (`"quando o usuário pedir X, filtre status = 'Y'"`) em instruções textuais — o que infla o prompt, cria conflitos e quebra quando novos valores chegam nos dados.
5. **Falsos negativos em avaliação:** comparar o SQL gerado pelo Genie por igualdade de string com um SQL gabarito reprova consultas perfeitamente corretas (por exemplo, `SUM(a)` vs `SUM(b.a)`, CTE vs subquery, aliases diferentes ou ordem de linhas sem `ORDER BY`).
6. **Falta de visibilidade executiva e auditoria:** liderança precisa saber, antes de liberar um Genie para usuários de negócio, qual é a assertividade real, a latência P50/P95, o Health Score e a evolução entre versões.

O **Databricks GenieOps** resolve essas 6 dores tratando Genie Agents como código versionado, auditável, testável e promovível (**Genie-as-Code**).

---

## Registro de Decisões Arquiteturais (ADRs)

### ADR-001 — Especificação declarativa em 4 YAMLs + compilação determinística `serialized_space` v2 (UUID5)

- **Decisão:** Cada Genie Space vive em `spaces/<nome>/` dividido em 4 arquivos temáticos (`space.yaml`, `sources.yaml`, `instructions.yaml`, `benchmarks.yaml`) compilados por `genieops/compiler.py` para o payload oficial **`serialized_space` v2** com arrays ordenados e IDs 32-hex gerados via **UUID5** determinístico.
- **Por quê (Negócio & Engenharia):**
  - O JSON bruto `serialized_space` da API Databricks é extenso, verboso e difícil de revisar em Pull Requests.
  - Separar em 4 arquivos permite **divisão clara de responsabilidades**: engenheiros de dados revisam `sources.yaml` e `join_specs`, enquanto especialistas de negócio revisam descrições, sinônimos e `benchmarks.yaml`.
  - IDs determinísticos (UUID5) e ordenação estável garantem **100% de idempotência**: compilar o mesmo Space duas vezes gera exatamente o mesmo hash/JSON, eliminando ruído em `git diff` e habilitando validação de determinismo no CI.
  - O parser reverso (`genieops pull`) garante adoção sem fricção em espaços já existentes no Databricks.

### ADR-002 — Hierarquia Oficial de Correção em 8 Camadas (Menor Superfície Estruturada Primeiro)

- **Decisão:** Tanto o linter (`linter.py`) quanto o diagnosticador (`diagnoser.py`) seguem rigorosamente a hierarquia oficial Databricks Genie Agents:
  1. Escopo e descrições de fontes (`sources.yaml`)
  2. `column_configs` (descrições, sinônimos, `exclude: true` em colunas técnicas)
  3. `enable_entity_matching` e `enable_format_assistance` seletivos em dimensões categóricas
  4. Metadados e medidas governadas de Metric Views (`MEASURE()`)
  5. `join_specs` validados por chaves PK/FK e grão
  6. `sql_snippets` reutilizáveis (`measures`, `filters`, `expressions`)
  7. `example_question_sqls` representativos por padrão de consulta
  8. `text_instructions` globais curtas (último recurso; máximo 1 item compilado)
- **Por quê:**
  - Corrigir na camada estruturada certa resolve **toda uma classe de perguntas** e acompanha automaticamente novos dados (ex.: `entity_matching` encontra novos segmentos sem editar instruções).
  - Jogar lógica específica de coluna ou valor em `text_instructions` cria "dívida de prompt", conflita com metadados do Unity Catalog e piora a assertividade geral.
  - O comando `genieops diagnose` **nunca auto-muta** um Space: ele classifica a causa raiz com evidências e propõe o plano de correção para aprovação humana consciente.

### ADR-003 — Avaliação em 3 Camadas: Estrutura SQL + Equivalência Matemática de Result Sets + LLM-as-a-Judge Plugável

- **Decisão:** O motor de benchmark (`benchmark.py`, `comparator.py`, `agent_mode.py`, `judges.py`) suporta 4 modos (`offline`, `live`, `eval-run`, `agent`) e avalia respostas por:
  1. **Validação estrutural/semântica** (offline, custo zero — ideal para PRs e CI);
  2. **Equivalência matemática de Result Sets** (executa SQL esperado e SQL gerado read-only no Warehouse, normaliza nomes/ordem de colunas, aplica tolerância relativa/absoluta para decimais e só exige ordem de linhas quando há `ORDER BY ... LIMIT`);
  3. **Streaming SSE da Agent Mode API + LLM-as-a-Judge plugável** (`heuristic`, `databricks` FMAPI ou `openai` compatível) para perguntas complexas multi-etapa ou documentais sobre UC Volumes.
- **Por quê:**
  - Comparar strings SQL gera excesso de falsos negativos e desestimula a equipe a manter benchmarks.
  - A API nativa de Conversation ignora UC Volumes; suportar a **Agent Mode API via SSE** (`/api/2.0/genie/agents/{space_id}/responses`) viabiliza testar agentes híbridos (tabelas + PDFs/políticas em Volumes), capturar `reasoning`, `execute_sql`, `search_context_files` e citações `[n](url)`, além de detectar indexação pendente (`volume_content_search_failed`).
  - Tornar o LLM-as-a-Judge plugável evita vendor lock-in e permite rodar testes de rubrica offline (`heuristic`) no CI e avaliação profunda via Databricks Foundation Model API em homologação.

### ADR-004 — Prevenção Ativa de Benchmark Leakage

- **Decisão:** O linter bloqueia (`LEAK001`) qualquer `example_question_sqls` que copie a pergunta ou SQL (exato ou similaridade >= 92%) de `benchmarks.yaml`.
- **Por quê:**
  - Copiar casos do benchmark para `example_question_sqls` faz o score subir artificialmente para ~100% sem que o Genie realmente saiba generalizar para perguntas novas dos usuários em produção.
  - Exemplos devem ensinar **padrões estruturais** (usando recortes/períodos distintos), enquanto benchmarks medem **generalização real**.

### ADR-005 — Separação Estrita de Segurança: Read-Only Guard vs Allowlist de Exportação Delta UC

- **Decisão:**
  - Toda operação de profiling, `EXPLAIN`, comparação de Result Sets, `system.query.history` e `system.access.audit` passa obrigatoriamente por `assert_read_only_sql` (`SELECT`/`WITH`/`SHOW`/`DESCRIBE`/`EXPLAIN`), bloqueando qualquer DDL/DML.
  - A exportação do histórico para Delta no Unity Catalog (`uc_export.py`) funciona em **dry-run seguro por padrão** (gera script `.sql` revisável) e só executa no Warehouse com `--execute` explícito passando por `assert_uc_export_sql_safe`, que permite **exclusivamente** `CREATE TABLE IF NOT EXISTS`, `MERGE INTO` e `INSERT INTO` nas 5 tabelas oficiais `genie_opt_*` dentro do `<catalog>.<schema>` aprovado.
- **Por quê:**
  - Garante princípio do menor privilégio e confiança para equipes de Governança de Dados aprovarem o toolkit em workspaces corporativos de produção: nenhuma tabela de negócio pode jamais ser alterada ou apagada pelo GenieOps.

### ADR-006 — Deploy Seguro com Backup Automático Pré-`update-space`

- **Decisão:** Antes de executar `databricks genie update-space`, o `deployer.py` baixa o snapshot completo do Space remoto e grava em `.genieops/backups/<space>/<env>/<timestamp>.json`. Além disso, `deploy` bloqueia automaticamente se o `lint` encontrar erros (a menos que `--skip-lint` seja explícito).
- **Por quê:**
  - A API `update-space` do Databricks realiza **substituição total (full replacement)**. Um backup automático pré-deploy transforma qualquer incidente em um rollback de segundos.

### ADR-007 — Promoção Multi-Ambiente sem Segredos Hardcoded

- **Decisão:** Configurações por ambiente ficam em `env/<env>.yaml` (defaults globais) + `space.yaml` (overrides por Space), autenticando exclusivamente via **perfis do Databricks CLI** (`--profile`) ou variáveis de ambiente em CI/CD (`.env.example`). O `migrator.py` remapeia `catalog`, `schema` e `/Volumes/...` em todas as superfícies (`sources`, `join_specs`, `sql_snippets`, `example_question_sqls`, `benchmarks`).
- **Por quê:**
  - Elimina risco de vazamento de PATs, client secrets ou URLs internas no Git.
  - Permite manter **uma única fonte de verdade** em YAML promovida com segurança de `dev` → `qa` → `prod`.

### ADR-008 — Observabilidade Local-First (SQLite WAL + FastAPI/React na Porta `8765`) + Persistência Opcional em Delta UC

- **Decisão:**
  - Histórico local em **SQLite WAL** (`.genieops/history.db`) com cálculo de regressão (`fixed`, `regressed`, `unchanged`) e latência média/P50/P95.
  - **Painel Web Local** (`genieops serve`, porta padrão `8765` para evitar conflito com `8080`/`3000`/`8000`) combinando API FastAPI + interface React/TypeScript/Vite/Tailwind.
  - Exportação opcional para as tabelas Delta oficiais Databricks (`genie_opt_runs`, `genie_opt_config_versions`, `genie_opt_eval_results`, `genie_opt_repair_analysis` ou tabela única `genie_opt_events`).
- **Por quê:**
  - Qualquer desenvolvedor ou analista consegue rodar o framework completo em 2 minutos na própria máquina, com zero infraestrutura extra.
  - Quando a organização escala para dezenas de Genie Spaces, basta ativar `genieops export-delta` em CI/CD para consolidar métricas de qualidade no Lakehouse e criar dashboards corporativos de governança AI/BI.

### ADR-009 — Curadoria Guiada por Evidência Real (`sqlglot` AST Profiling + `system.access.audit`)

- **Decisão:**
  - `genieops profile --query-history` faz parsing AST (dialeto Databricks via `sqlglot`) das consultas recentes de `system.query.history` para descobrir automaticamente JOINs frequentes, filtros `WHERE` recorrentes e medidas agregadas.
  - `genieops harvest-feedback --include-audit` combina conversas com falha/thumbs-down com eventos de `system.access.audit` (`updateConversationMessageFeedback`, `createConversationMessageComment`), aplicando **deduplicação semântica** (Jaccard + `SequenceMatcher`) e descartando perguntas já cobertas em `benchmarks.yaml`.
- **Por quê:**
  - Fecha o **ciclo contínuo de melhoria (flywheel)**: perguntas reais que falharam em produção viram automaticamente novos casos de benchmark (lock-in de regressão), e o padrão real de uso SQL dos analistas acelera a curadoria inicial sem achismo.

### ADR-010 — Governança de Agentes de IA Versionada no Repositório (`GEMINI.md` + `.agents/rules/`)

- **Decisão:** Versionar as regras arquiteturais, invariantes Databricks Genie e portão de qualidade em `GEMINI.md` e `.agents/rules/*.md`.
- **Por quê:**
  - Garante que qualquer futura sessão assistida por agentes de IA respeite automaticamente as mesmas regras de segurança, schema v2, testes offline e commits semânticos sem precisar reexplicar o contexto do projeto.

### ADR-011 — Trusted Assets (`sql_functions`), Robustez via Paráfrases, Rodadas Rotuladas e Kit Star Schema/UC COMMENTs

- **Decisão:**
  - Suportar `instructions.sql_functions` (Unity Catalog SQL UDFs / Trusted Assets) de ponta a ponta no schema YAML, compilador determinístico v2 (IDs UUID5 + ordenação `(id, identifier)`), parser reverso (`pull`), `diff_payloads`, `migrator.py`, `linter.py` (`SQLF001`), documentação e Painel Web.
  - Suportar `paraphrases` em cada `BenchmarkCase` (`benchmarks.yaml`) com expansão opcional (`--expand-paraphrases`) na compilação e execução de benchmarks, além de incluir paráfrases na guarda contra Benchmark Leakage (`LEAK001`).
  - Persistir rótulos de rodada (`label`) no SQLite (`benchmark_runs.label` com migração automática retrocompatível), na exportação Delta (`genie_opt_runs.notes` / `genie_opt_events.payload_json`) e na **Tabela de Evolução da Acurácia por Rodada** dos relatórios MD/HTML (`docs_generator.py`).
  - Disponibilizar em `curation_kit.py` os geradores offline revisáveis `genieops uc-comments` (`COMMENT ON TABLE` / `ALTER COLUMN COMMENT`) e `genieops seed-star-schema` (base fictícia em esquema estrela com 6 armadilhas reais de negócio + DDL de Trusted Assets + playbook de rodadas 0→4), preservando estritamente a política de zero mutação não autorizada no Unity Catalog.
- **Por quê:**
  - **Trusted Assets (`sql_functions`):** resolvem métricas não-aditivas, rankings parametrizados e cálculos metodológicos governados onde Metric Views ou snippets simples não bastam.
  - **Paráfrases (2–4 variações por pergunta):** medem generalização linguística real em vez de memorização de uma única formulação.
  - **Rodadas rotuladas + Kit Star Schema/COMMENTs:** permitem executar e documentar cientificamente a curadoria progressiva (Rodada 0 só tabelas → +UC COMMENTs → +Text Instructions → +SQLs de exemplo → +SQL Functions), registrando cada degrau de acurácia em Delta e nos relatórios executivos.
