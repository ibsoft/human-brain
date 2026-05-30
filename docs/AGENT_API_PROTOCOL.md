# Agent API Protocol

This document defines how AI agents should use Human-Brain for long-term memory, semantic retrieval, context building, file/image memory, and correlations.

## Authentication

Agents authenticate with an API key:

```http
X-API-Key: hb_...
Content-Type: application/json
```

The API key identifies the agent. If `agent_id` is sent, it must match the API key owner.

## Memory Search Protocol

Endpoint:

```http
POST /api/v1/memory/search
```

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

File memories:

- extract text from TXT, LOG, MD, CSV, JSON, YAML, XML
- extract PDF text when `pypdf` or `PyPDF2` is installed
- extract DOCX text when `python-docx` is installed
- extract XLSX/XLSM text when `openpyxl` is installed
- store document keyword vectors for correlation

Image memories:

- store the original image locally
- expose an authenticated asset URL
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
