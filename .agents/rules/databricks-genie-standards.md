---
trigger: model_decision
description: "Padrões técnicos oficiais de Databricks Genie Agents (serialized_space v2, Agent Mode SSE, Metric Views, UC Persistence Delta e hierarquia de curadoria). Aplicar ao editar spaces/, compiler.py, linter.py, diagnoser.py, benchmark.py, agent_mode.py ou uc_export.py."
---

# Padrões Técnicos Databricks Genie Agents

## Schema `serialized_space` v2
- `version`: sempre `2`.
- `config.sample_questions[]`: ordenado por `id` (32-hex).
- `data_sources.tables[]`: tabelas e Metric Views ordenadas por `identifier`; `column_configs[]` ordenado por `column_name`.
- `data_sources.volumes[]`: caminhos iniciando com `/Volumes/<catalog>/<schema>/<volume>`, máximo 10 volumes.
- `instructions.text_instructions[]`: máximo 1 item compilado; strings individuais <= 25.000 chars.
- `instructions.join_specs[]` e `instructions.sql_snippets.{measures,filters,expressions}[]`: **todas as colunas devem ser qualificadas com tabela ou alias** para evitar `Table name or alias is required for column`.
- `benchmarks.questions[]`: **sempre no nível raiz** (nunca dentro de `instructions`). Casos `agent` sem SQL canônico usam `answer: [{"format": "SQL", "content": []}]` + `evaluation_note`.
- Tamanho total do JSON compilado <= 3.5 MB.

## Metric Views
- Consultas sobre Metric Views devem usar `MEASURE(<medida>)`.
- Nunca colocar `MEASURE()` na cláusula `WHERE` ou `GROUP BY` — filtrar via `HAVING` ou CTE/subquery externa.

## Agent Mode API (SSE)
- Endpoint: `POST {host}/api/2.0/genie/agents/{space_id}/responses` com `Accept: text/event-stream`.
- Eventos suportados: `response.created`, `reasoning`, `function_call` (`execute_sql`, `search_context_files`), `function_call_output`, `message`, `response.completed`, `response.failed`.
- Tratar `error.code == "volume_content_search_failed"` como indexação de volume ainda em andamento.
- Para cancelar respostas longas: `databricks genie genie-cancel-response SPACE_ID CONVERSATION_ID RESPONSE_ID`.

## Persistência em Unity Catalog (Delta)
- Seguir estritamente o schema oficial de 4 tabelas (`genie_opt_runs`, `genie_opt_config_versions`, `genie_opt_eval_results`, `genie_opt_repair_analysis`) ou tabela única de eventos (`genie_opt_events`).
- Nunca misturar operações de escrita de exportação com o caminho `execute_readonly_sql`.
