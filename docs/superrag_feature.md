# superRAG

Status: Stable core workflow.

`superrag_agent` is one of Kendr's primary product workflows. It provides a session-based RAG pipeline that can ingest mixed sources and then serve chat retrieval over that indexed knowledge.

## Supported Sources

- Local paths (`--superrag-path` / `superrag_local_paths`)
- URLs (`--superrag-url` / `superrag_urls`)
- Database URL (`--superrag-db-url` / `superrag_db_url`)
- OneDrive (Microsoft Graph) (`--superrag-onedrive` + `--superrag-onedrive-path`)

## Modes

- `build`: ingest + chunk + embed + vector index
- `chat`: ask questions against an indexed session
- `switch`: switch active superRAG session
- `list`: list available superRAG sessions
- `status`: show session stats, ingestion history, and recent chat entries

## CLI Examples

Build a new session from local files + URLs:

```bash
kendr run "build my superRAG knowledge base" \
  --superrag-mode build \
  --superrag-new-session \
  --superrag-session-title "finance-kb" \
  --superrag-path ./docs \
  --superrag-url https://example.com/reports
```

Build from database URL and store schema knowledge:

```bash
kendr run "index db" \
  --superrag-mode build \
  --superrag-session finance_db \
  --superrag-db-url "postgresql://user:pass@host:5432/dbname" \
  --superrag-db-schema public
```

Chat with an existing session:

```bash
kendr run "ask rag" \
  --superrag-mode chat \
  --superrag-session finance_db \
  --superrag-chat "What are the top revenue drivers in the indexed data?"
```

Switch sessions:

```bash
kendr run "switch rag session" \
  --superrag-mode switch \
  --superrag-session finance_db
```

List sessions:

```bash
kendr run "list rag sessions" --superrag-mode list
```

## Gateway Payload Keys

You can post these to `POST /ingest`:

- `superrag_mode`
- `superrag_session_id`
- `superrag_new_session`
- `superrag_session_title`
- `superrag_local_paths`
- `superrag_urls`
- `superrag_db_url`
- `superrag_db_schema`
- `superrag_onedrive_enabled`
- `superrag_onedrive_path`
- `superrag_chat_query`
- `superrag_top_k`

## Progress and ETA

During `build` mode, the agent emits:

- preflight source analysis
- estimated processing time and chunk estimate
- step-level status (local/URL/DB/OneDrive ingestion)
- indexing progress notifications

These logs are sent through normal task updates so they appear in runtime/console monitoring.

## Persistence

The feature stores state in SQLite:

- `superrag_sessions`
- `superrag_ingestions`
- `superrag_chat_messages`

Each session maps to its own vector collection (`superrag_<session_id>`), enabling clean session switching.
