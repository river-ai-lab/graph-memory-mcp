# Graph Memory MCP — agent notes

Python MCP server (`graph_memory_mcp/`). FalkorDB backend; optional `--simple` profile.

## Before commit

Use the personal skill **`/pre-commiter`** or **@pre-commiter** (`~/.cursor/skills/pre-commiter/`).

For this repo specifically:

- **Full suite (required before commit):** FalkorDB must be running (Docker). Then:
  ```bash
  ./scripts/test.sh
  # or: docker compose up -d && uv run pytest -q
  ```
- Hooks: `uv run pre-commit run --all-files`
- Docs: `docs/`, index at `docs/__index.md`
- Relation allowlist: `graph_memory_mcp/graph_memory/relation_policy.py`, env `RELATION_*`
- LLM link rules: `docs/memory_policies_for_LLM.md` → Relations; cheatsheet: `docs/memory_policy_cheatsheet.md`

## Layout

| Path | Role |
|------|------|
| `graph_memory_mcp/server.py` | Full MCP (nested `source`, `upsert_node`) |
| `graph_memory_mcp/server_simple.py` | Simple MCP (flat provenance, no `upsert_node`) |
| `graph_memory_mcp/cli.py` | `--simple` flag |
| `tests/test_graph_memory_server.py` | Server + integration tests |
| `graph_memory_mcp/explorer/` | Local graph explorer GUI (`graph-memory-explorer`) |

## Память (MCP: `graph-memory-mcp`)

Работай с сервисом памяти — это долговременная память для агентов и база знаний лаборатории, общая для всех агентов и сессий. Контекст чата конечен; решения, договорённости, архитектура проектов и проверенные факты должны жить в памяти, а не теряться между запусками.

Политики: [docs/memory_policies_for_LLM.md](docs/memory_policies_for_LLM.md), шпаргалка: [docs/memory_policy_cheatsheet.md](docs/memory_policy_cheatsheet.md). Этот файл задаёт константы оператора — применяй, не выдумывай.

### Обязательный ритуал

1. **Старт задачи** — `get_brief(owner_id="riverlab")` → при теме задачи `search(..., compact=true)` → follow `suggested_next` / `get_context` на лучших hits; путь между двумя id — `get_trace` (directed; пусто → `directed=false`).
2. **Новое устойчивое знание** — `search` → нет дубля → `create_node`; смотри `possible_duplicates` в ответе (дубль → link/update; конфликт → `CONTRADICTS` или `mark_outdated`).
3. **После meaningful work (GROW)** — перед финальным ответом пользователю (не откладывай на «конец сессии»):
   1. **Ground** — что устойчивого изменилось? (если ничего — стоп, не пиши)
   2. **Record** — `search` → `create_node` / `mark_outdated`+`create_node`
   3. **Orient** — recurring? → `tags=["pattern"]` или relation (не на каждый чих)
   4. **Write** — `metadata.project` + `created_by`

`recall_context` — optional one-call shortcut; не заменяет цепочку выше. Документ/длинный разговор → extract → `ingest_knowledge` (см. политики).

**Пиши, если:** решение, договорённость, root cause, архитектурный вывод — одно declarative утверждение на node.
**Не пиши:** очевидное из README, временный дебаг, секреты/PII, scratchpad, сырой диалог.

MCP недоступен — работай без памяти, сообщи пользователю.

### Константы оператора

| Константа | Значение | Где |
|-----------|----------|-----|
| **`owner_id`** | `"riverlab"` | **Всегда** на каждый вызов. Общая память лаборатории. |
| **`project`** | `"graph-memory-mcp"` | Soft partition: запись — `metadata.project`; чтение — `metadata_filter={"project": "graph-memory-mcp"}` (без фильтра — кросс-проектный recall). |
| **`created_by`** | опционально, напр. `"agent:…"` / `"user:…"` | Attribution на записи: `metadata.created_by`. |
| **`node_type`** | `"Fact"` или `"Entity"` | Fact = утверждение; Entity = именованная сущность. |
| **`text`** | одно чёткое утверждение | Substance в `text`, не в metadata. |
| **`metadata`** | reserved: `project`, `created_by`, `tags`, `type`, `confidence` | Неверные типы отвергаются; прочие ключи — free-form. |
| **`query`** | вопрос / ключевые слова | Обязателен в `search` вместе с `owner_id`. |

### Поведение

- Перед `create_node` — `search` с тем же `owner_id`.
- Факт стал неверным — `mark_outdated` + `create_node`; опечатка/metadata — `update_node`.
- Связи: `RELATED_TO`, `MENTIONS`, `SUMMARIZES`, `FOLLOWS_FROM`, `CONTRADICTS` (+ allowlist команды) — не выдумывай типы.
- Не пиши секреты, PII, сырой диалог, временный дебаг.
