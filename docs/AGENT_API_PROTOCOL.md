# Agent API Protocol

This document defines how AI agents should use Human-Brain for long-term memory, semantic retrieval, context building, file/image memory, and correlations.

## Client Variables

Set these once in the agent environment before calling the API:

```bash
export HUMAN_BRAIN_URL=http://localhost:5000
export HUMAN_BRAIN_API_KEY=hb_REPLACE_ME
export HUMAN_BRAIN_WORKSPACE_ID=1
```

## Authentication

Agents authenticate with an API key:

```bash
curl "$HUMAN_BRAIN_URL/api/v1/vector/health" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

The API key identifies the agent. If `agent_id` is sent, it must match the API key owner.

## Source-Of-Truth Agent Policy

Agents should treat Human-Brain as the only durable source of truth for remembered state. Before answering from prior context, project history, user preferences, tasks, decisions, files, images, sessions, or local facts, the agent must search Human-Brain. If no relevant memory exists, the agent should say no stored memory was found and use only the current conversation or ask for the missing fact.

Agents should store new durable facts, decisions, tasks, preferences, corrections, and session outcomes back into Human-Brain. When information changes, agents should update, archive, delete, or forget stale memories instead of silently relying on old facts.

Use `docs/agents/SKILL.md` as the full agent operating instruction pack. It covers search, add, update, delete, forget, sessions, consolidation, workspaces, correlations, vision, assets, health checks, and answer rules.

## Memory Search Protocol

Endpoint:

```http
POST /api/v1/memory/search
```

Use `$HUMAN_BRAIN_URL/api/v1/memory/search` when calling it over HTTP.

Recommended request:

```json
{
  "workspace_id": 1,
  "query": "What do we know about PostgreSQL backups for production?",
  "top_k": 8,
  "include_vector_details": true,
  "include_correlations": true,
  "correlation_limit": 5,
  "include_timing": true,
  "memory_types": ["technical_notes", "project", "task", "facts"],
  "min_trust": 0.2
}
```

Response fields:

- `memory`: full memory record
- `relevance_score`: final hybrid ranking score
- `semantic_score`: FAISS/vector score
- `vector_score`: same score exposed explicitly for agents
- `explanation`: score components
- `vector`: embedding metadata when requested
- `correlations`: related memories when requested
- `agent_evidence`: concise payload designed for direct agent reasoning
- `timing.elapsed_ms`: end-to-end search time in milliseconds

Agents should use:

1. High `relevance_score` first.
2. `semantic_score` to understand vector match quality.
3. `trust_score` and `importance_score` before using a memory as fact.
4. Correlations to pull adjacent project/task/file/image context.
5. `assets[].url` when an image or uploaded file should be referenced.
6. `timing.elapsed_ms` to monitor retrieval latency.

## Correlation Protocol

Endpoint:

```http
GET /api/v1/memory/{memory_id}/correlations?workspace_id=1&limit=10
```

Use `$HUMAN_BRAIN_URL/api/v1/memory/{memory_id}/correlations?workspace_id=1&limit=10` when calling it over HTTP.

Use this when an agent already has a memory and wants its neighborhood.

The response includes:

- selected memory
- related memories
- correlation strength
- correlation explanation
- asset links and metadata on related memories

## Context Builder Protocol

Endpoint:

```http
POST /api/v1/context/build
```

Use `$HUMAN_BRAIN_URL/api/v1/context/build` when calling it over HTTP.

Recommended request:

```json
{
  "workspace_id": 1,
  "prompt": "Continue the deployment project and list open risks.",
  "top_k": 10,
  "max_tokens": 1600,
  "sensitivity_policy": "strict",
  "include_correlations": true,
  "correlation_limit": 3
}
```

The context builder applies the Memory Firewall. High/secret memories are blocked when strict policy is active.

## File and Image Memories

Uploaded files and images become memories with assets.

Endpoint:

```http
POST /api/v1/memory/upload
```

Agents upload files with multipart form data, not JSON. Do not send `Content-Type: application/json` for this endpoint; let the HTTP client set the multipart boundary.

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/upload" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -F "workspace_id=$HUMAN_BRAIN_WORKSPACE_ID" \
  -F "title=Reference document" \
  -F "memory_type=technical_notes" \
  -F "confirmed=true" \
  -F "ingest_mode=full" \
  -F "uploads=@/path/to/reference.pdf"
```

For long documents, use chunked ingestion:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/upload" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -F "workspace_id=$HUMAN_BRAIN_WORKSPACE_ID" \
  -F "title=Long report" \
  -F "memory_type=project" \
  -F "ingest_mode=chunks" \
  -F "chunk_size=4000" \
  -F "uploads=@/path/to/report.docx"
```

Use the `uploads` field for one or more files, or `file` for a single file. `ingest_mode=full` creates one memory per document. `ingest_mode=chunks` creates one memory per text chunk. Images are stored as image assets and usually use `memory_type=vision`.

Common multipart fields:

- `workspace_id`: required workspace for the stored memories.
- `uploads`: one or more files.
- `file`: optional single-file alias.
- `title`: base title. Chunked documents append `- chunk N`.
- `memory_type`: defaults to `long-term`; use `vision` for uploaded images.
- `tags`: comma-separated tags.
- `confirmed`: `true` or `false`.
- `sensitivity_level`: `normal`, `high`, or `secret`.
- `importance_score` and `trust_score`: numbers from `0` to `1`.
- `ingest_mode`: `full` or `chunks`.
- `chunk_size`: characters per chunk when `ingest_mode=chunks`; default `4000`.

The response contains `count` and `memories[]`. Each memory includes `assets[]`; use `assets[].url` to open the tokenized file/image URL from remote clients when `HUMAN_BRAIN_URL` is configured on the server.

Replace the actual uploaded file for an existing document/image memory:

```http
POST /api/v1/memory/{memory_id}/asset/replace
```

Use multipart form data:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/123/asset/replace" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -F "title=Updated reference document" \
  -F "file=@/path/to/replacement.pdf"
```

The replacement endpoint keeps the existing memory ID and tokenized asset URL, replaces the stored file, refreshes extracted text or image metadata, refreshes asset vectors and FAISS memory vectors, and reruns correlations. Use `title` or `tags` multipart fields to update those memory fields during replacement. Do not use `ingest_mode=chunks` for replacement; upload a new chunked document when chunk boundaries need to change.

File memories:

- extract text from TXT, LOG, MD, CSV, JSON, YAML, XML
- extract PDF text when `pypdf` or `PyPDF2` is installed
- extract DOCX text when `python-docx` is installed
- extract XLSX/XLSM text when `openpyxl` is installed
- store document keyword vectors for correlation

Image memories:

- store the original image locally
- expose a tokenized asset URL
- store metadata such as width, height, color profile, dominant color
- store a local visual vector/fingerprint
- correlate with other images, files, notes, and text memories through tags, metadata, and vector similarity

## Production Install With PostgreSQL, Redis, Celery

Minimum services:

- PostgreSQL
- Redis
- web process running Gunicorn
- Celery worker
- Celery beat if scheduled jobs are enabled

Environment:

```env
FLASK_ENV=production
SECRET_KEY=change-me
DATABASE_URL=postgresql+psycopg://human_brain:password@postgres:5432/human_brain
REDIS_URL=redis://redis:6379/2
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
SESSION_COOKIE_SECURE=true
CORS_ENABLED=false
```

Install:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-core.txt
pip install -r requirements-ml.txt
flask --app manage:app db upgrade
gunicorn -c gunicorn.conf.py manage:app
```

Worker:

```bash
celery -A manage.celery worker --loglevel=INFO
```

Beat:

```bash
celery -A manage.celery beat --loglevel=INFO
```

Docker Compose:

```bash
docker compose up --build
docker compose exec web flask --app manage:app db upgrade
docker compose exec web python manage.py seed-demo-data
```

## Agent Retrieval Checklist

Before answering a user:

1. Call `/api/v1/memory/search`.
2. Request vector details and correlations.
3. Prefer confirmed, high-trust memories.
4. Review correlated project/task/file/image memories.
5. Use asset links when the answer references uploaded files or images.
6. Call `/api/v1/context/build` for a final prompt-ready context block.
7. Never inject high/secret memories unless policy permits it.
