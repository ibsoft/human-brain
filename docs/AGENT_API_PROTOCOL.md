# Agent API Protocol

This document defines how AI agents should use Human-Brain for long-term memory, semantic retrieval, context building, file/image memory, vision scene memory, sessions, health checks, and correlations.

## Client Variables

At startup, load required environment variables from `/etc/hermes/environment.conf` before calling Human-Brain or other Hermes services:

```bash
set -a
. /etc/hermes/environment.conf
set +a
```

Then ensure these variables exist:

```bash
export HUMAN_BRAIN_URL=http://localhost:5000
export HUMAN_BRAIN_API_KEY=hb_REPLACE_ME
export HUMAN_BRAIN_WORKSPACE_ID=1
export HUMAN_BRAIN_AGENT_ID=1
```

## Authentication

Agents authenticate with an API key:

```bash
curl "$HUMAN_BRAIN_URL/api/v1/vector/health" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

The API key identifies the agent. If `agent_id` is sent, it must match the API key owner.

## Source-Of-Truth Agent Policy

Agents should treat Human-Brain as the only durable source of truth for remembered state, project context, tasks, notes, decisions, preferences, sessions, uploaded files, images, vision observations, health findings, and prior instructions. Before answering from prior context, project history, user preferences, tasks, decisions, files, images, sessions, or local facts, the agent must search Human-Brain. If no relevant memory exists, the agent should say no stored memory was found and use only the current conversation or ask for the missing fact.

Agents should store new durable facts, decisions, tasks, preferences, corrections, blockers, commands tried, tests run, project status, vision observations, and session outcomes back into Human-Brain. When information changes, agents should update, archive, delete, or forget stale memories instead of silently relying on old facts. Agents should avoid duplicates by searching before writing and updating or strengthening existing memories when they already capture the same durable fact.

Agents should use sessions for meaningful work. Start a session before a multi-turn task, include `session_id` on memories and context requests when relevant, add important messages, end the session, then consolidate it into durable memories.
When Settings -> Require agents to use sessions is enabled, Human-Brain also auto-captures request/response pairs into `session_messages` for agent API calls that include a valid numeric `session_id`.

Use `docs/agents/SKILL.md` as the full agent operating instruction pack. It covers search, add, update, delete, forget, sessions, consolidation, workspaces, correlations, vision, assets, health checks, and answer rules.

Operators can also download the Skill and Protocol files from Settings -> Agent System Prompt.

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
- `agent_policy`: enforcement guidance. Treat `search_before_answer=true` as a hard operating rule and write back durable outcomes after the work.

Agents should use:

1. High `relevance_score` first.
2. `semantic_score` to understand vector match quality.
3. `trust_score` and `importance_score` before using a memory as fact.
4. Correlations to pull adjacent project/task/file/image context.
5. `assets[].url` when an image or uploaded file should be referenced.
6. `timing.elapsed_ms` to monitor retrieval latency.

Compact agent search results include `assets[]` when a memory has uploaded assets. When the user asks to see an uploaded image or document again, use `assets[].url`; do not answer with only the stored text description.

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

## Memory Quality And Enforcement

Human-Brain records agent searches and context builds as policy evidence. Before writing durable memory, search or build context in the same workspace. Memory writes return:

- `quality.score`, `quality.level`, and `quality.warnings`
- `agent_policy.search_before_write_ok`
- `agent_policy.warnings`, including `search_before_write_missing` when a write happened without recent retrieval

Operators can make low-quality writes or no-search writes strict in Settings. Even when strict mode is off, agents must treat these warnings as defects to correct: search, update existing memories when possible, and write one clear memory only when the information is materially new.

Task memories may include `task_status`, `task_priority`, `task_owner`, `task_due_at`, `task_next_action`, `task_acceptance_criteria`, and `task_dependencies`. Human-Brain normalizes these into searchable workflow fields and tags.

Project memories may include `project_status`, `project_goal`, `project_phase`, `project_next_actions`, `project_decisions`, `project_risks`, and `project_open_questions`.

Quality and cleanup endpoints:

```http
GET /api/v1/memory/quality-report?workspace_id=1
GET /api/v1/memory/stale?workspace_id=1&page=1&per_page=25
```

Use the quality report before cleanup work. It reports low-quality memories, duplicate groups, and stale active memories.

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
  -F "session_id=$SESSION_ID" \
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
  -F "session_id=$SESSION_ID" \
  -F "title=Long report" \
  -F "memory_type=project" \
  -F "ingest_mode=chunks" \
  -F "chunk_size=4000" \
  -F "uploads=@/path/to/report.docx"
```

Use the `uploads` field for one or more files, or `file` for a single file. `ingest_mode=full` creates one memory per document. `ingest_mode=chunks` creates one memory per text chunk. Images are stored as image assets and usually use `memory_type=vision`.

Common multipart fields:

- `workspace_id`: required workspace for the stored memories.
- `session_id`: optional active numeric session ID. When present, uploads are linked to the session and auto-captured in the session replay.
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

The response contains `count` and `memories[]`. Each memory includes `assets[]`; use `assets[].url` to open the tokenized file/image URL from remote clients. Operators should configure Settings -> Public base URL, or `.env` `HUMAN_BRAIN_URL`, to the externally reachable reverse-proxy URL.

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

## Sessions and Jobs

Agents must create and use sessions for meaningful tasks:

```bash
SESSION_ID=$(curl -s -X POST "$HUMAN_BRAIN_URL/api/v1/session/start" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d "{\"workspace_id\":$HUMAN_BRAIN_WORKSPACE_ID,\"title\":\"User task\"}" | python -c 'import sys,json; print(json.load(sys.stdin)["session_id"])')
```

Carry the returned numeric `SESSION_ID` through all related calls:

```json
{
  "workspace_id": 1,
  "session_id": 123,
  "query": "Search question"
}
```

Human-Brain only knows which session to write when the request includes `session_id`, or when the agent explicitly calls `/api/v1/session/add-message`. Starting a session alone creates an empty session until messages or session-aware API calls are added.

Add important messages:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/session/add-message" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d "{\"session_id\":$SESSION_ID,\"role\":\"user\",\"content\":\"User request or durable decision.\"}"
```

End and consolidate:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/session/end" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d "{\"session_id\":$SESSION_ID}"

curl -X POST "$HUMAN_BRAIN_URL/api/v1/session/consolidate" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d "{\"session_id\":$SESSION_ID}"
```

Jobs are background worker records, currently used for session consolidation. The dashboard job count shows queued, running, completed, and failed jobs.

List jobs:

```bash
curl "$HUMAN_BRAIN_URL/api/v1/jobs?workspace_id=$HUMAN_BRAIN_WORKSPACE_ID" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

Get one job:

```bash
curl "$HUMAN_BRAIN_URL/api/v1/jobs/123" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

## Operations

Admins can enable agent API JSONL logging in Settings. Logs are rotated and visible under Agent Logs, with request body, response body, status, method, path, and agent id. Use this to debug what an agent sent and how Human-Brain answered.

Admins can enable scheduled duplicate consolidation in Settings. The duplicate consolidation worker finds exact or near-duplicate memories, writes one consolidated memory, and optionally archives the duplicate source memories.

Admins can enable scheduled system health checks in Settings. Celery beat evaluates the configured hourly, daily, or weekly policy and records each due run. Health checks verify database reachability, runtime directory writability, FAISS index state, vector mappings, orphan vectors, and memories missing vectors. When automatic repair is enabled, the worker rebuilds affected FAISS workspace indexes. Operators can also queue check-only or run-and-repair jobs from the System Health page and inspect paged run history.

Backup archives can be created, downloaded, restored, or deleted from the Backups page.

Settings -> Agent System Prompt provides short and long copyable prompts plus downloadable Skill and Protocol files for configuring new agents.

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

Vision scene memories:

- are created from stable YOLO scene observations, not every frame
- use count-based scene signatures such as `cup:2|person:1`
- respect configured minimum confidence and stable-frame thresholds
- avoid duplicate scene memories inside the configured auto-save interval
- can attach the latest annotated snapshot when snapshot storage is enabled
- include object labels, counts, confidence, timestamp, source, and storage reason

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

1. Load `/etc/hermes/environment.conf` if not already loaded.
2. Call `/api/v1/memory/search`.
3. Request vector details and correlations.
4. Prefer confirmed, high-trust memories.
5. Review correlated project/task/file/image/vision memories.
6. Use asset links when the answer references uploaded files or images.
7. Call `/api/v1/context/build` for a final prompt-ready context block.
8. Never inject high/secret memories unless policy permits it.
9. Write back durable outcomes, corrections, tasks, and next steps before ending substantial work.
