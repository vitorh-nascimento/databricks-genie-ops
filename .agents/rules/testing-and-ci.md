---
trigger: model_decision
description: "Padrões de testes (pytest), mocking da Databricks CLI, linting (ruff), CI/CD e commits semânticos no repositório Databricks GenieOps. Aplicar ao criar ou modificar testes, workflows ou módulos Python/TypeScript."
---

# Testes, Mocks, Linting e Commits

## Testes Unitários (`tests/`)
- Todos os testes devem rodar 100% offline sem precisar de workspace Databricks ativo.
- Reutilizar `FakeCLIRunner`, `FakeCompletedProcess`, `make_json_response` e `mock_client_factory` de `tests/conftest.py`.
- Para chamadas HTTP/SSE (Agent Mode e LLM-as-a-Judge), injetar transporte mockado (`httpx.MockTransport` ou iterador de linhas SSE) — nunca disparar tráfego real em testes unitários.
- Para FastAPI (`web_api.py`), testar endpoints via `fastapi.testclient.TestClient` apontando para diretório temporário (`tmp_path`) e `HistoryStore(tmp_path / "history.db")`.
- Sempre cobrir casos de segurança: bloqueio de SQL mutante em `assert_read_only_sql` e bloqueio de tabelas fora do padrão `genie_opt_*` no `uc_export`.

## Linting & Formatação
- Python: `.venv\Scripts\ruff.exe check genieops tests` (line-length 110, rules `E`, `F`, `I`, `UP`, target Python 3.11+).
- TypeScript/React (`web/`): `npm.cmd run build` (executa `tsc` + `vite build`). No PowerShell Windows, usar `npm.cmd` / `npx.cmd` para evitar bloqueio de ExecutionPolicy em `.ps1`.

## Commits Semânticos
- Usar prefixos padronizados: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.
- Executar `pytest` e `ruff` imediatamente antes do commit e confirmar `git status` limpo de artefatos temporários (`.genieops/staging/`, backups, `.env`).
