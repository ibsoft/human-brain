# Human-Brain

`Human-Brain` is a local/private long-term memory platform for AI agents. It stores short-term, episodic, long-term, task, project, preference, security-sensitive, archived, deleted/forgotten, and optional vision memories with workspace isolation, API-key controlled agent access, audit trails, semantic retrieval, session consolidation, and configurable privacy controls.

## Architecture

- Flask app factory with SQLAlchemy models, Alembic migrations, Flask-Login, CSRF, secure headers, and rate limiting.
- PostgreSQL in production; SQLite is suitable only for local development.
- FAISS indexes are persisted per workspace in `faiss_indexes/`. Each index uses normalized embeddings with `IndexIDMap2(IndexFlatIP)`, so FAISS returns stable `vector_id` values that are mapped through the `memory_vectors` table.
- `sentence-transformers` provides embeddings, with a deterministic fallback for constrained development environments.
- Redis + Celery run consolidation, FAISS rebuild, duplicate detection, trust scoring, expiration, backup, snapshot cleanup, and reports.
- Vision is a separate module. Camera access, snapshots, active model, backend, and available models are controlled on the Settings page. The initial model is `yolov8n.pt`, and additional Ultralytics YOLO models or local paths can be listed there.
- Memory correlation creates workspace-scoped graph edges between related memories. See `docs/MEMORY_CORRELATION.md`.
- Model operation guidance lives in `docs/models/SKILL.md`.
- Agent API protocol and retrieval behavior are documented in `docs/AGENT_API_PROTOCOL.md`.
- A ready-to-use agent skill lives in `docs/agents/SKILL.md`.

## Local Setup

```bash
cd human-brain
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-core.txt
# Optional, for local embeddings and YOLO vision:
pip install -r requirements-ml.txt
cp .env.local.example .env
export FLASK_ENV=development
export HUMAN_BRAIN_URL=http://localhost:5000
flask --app manage:app db init
flask --app manage:app db migrate -m "initial schema"
flask --app manage:app db upgrade
python manage.py seed-demo-data
python manage.py
```

Open `$HUMAN_BRAIN_URL`.
On first launch, `/login` redirects to `/setup` so you can create the first admin account in the browser.

## Demo And Sample Data

Create the default demo workspace, demo agent, and demo API key:

```bash
python manage.py seed-demo-data
```

Copy the printed `Demo API key` immediately; raw API keys are only shown when created.

Create richer sample data for testing search, context building, sessions, and correlations:

```bash
flask --app manage:app seed-sample-data --count 100
```

Remove generated sample data:

```bash
flask --app manage:app purge-sample-data
```

`purge-sample-data` deletes workspaces named `Sample%` and memories with `source=sample_seed`. It does not delete your normal default workspace or manually created memories unless they match those sample markers.

Rebuild correlations for existing data:

```bash
flask --app manage:app rebuild-correlations
```

For Docker Compose:

```bash
docker compose exec web python manage.py seed-demo-data
docker compose exec web flask --app manage:app seed-sample-data --count 100
docker compose exec web flask --app manage:app purge-sample-data
docker compose exec web flask --app manage:app rebuild-correlations
```

## Docker Compose

```bash
cd human-brain
cp .env.example .env
docker compose up --build
docker compose exec web flask --app manage:app db upgrade
docker compose exec web python manage.py seed-demo-data
```

Optional nginx profile:

```bash
docker compose --profile nginx up --build
```

## PostgreSQL Install

PostgreSQL is the recommended database for a durable installation. SQLite is useful for local development, but production installs should use PostgreSQL plus Redis.

### Option A: PostgreSQL With Docker Compose

This is the fastest PostgreSQL setup because `docker-compose.yml` already includes `postgres:16`, `redis:7-alpine`, the web app, Celery worker, and Celery beat.

1. Create the environment file:

```bash
cp .env.example .env
```

2. Edit `.env` and change secrets before first start:

```env
FLASK_ENV=production
HUMAN_BRAIN_URL=https://human-brain.example.lan
SECRET_KEY=replace-this-with-a-long-random-secret
DATABASE_URL=postgresql+psycopg://human_brain:human_brain@postgres:5432/human_brain
REDIS_URL=redis://redis:6379/2
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
RATELIMIT_STORAGE_URI=redis://redis:6379/3
SESSION_COOKIE_SECURE=false
FAISS_INDEX_DIR=/app/faiss_indexes
SNAPSHOT_DIR=/app/uploads/snapshots
```

`docker-compose.yml` currently creates PostgreSQL with `POSTGRES_USER=human_brain`, `POSTGRES_PASSWORD=human_brain`, and `POSTGRES_DB=human_brain`. If you change the database password or username in `.env`, change the matching `postgres.environment` values in `docker-compose.yml` before the first `docker compose up`. PostgreSQL only uses those `POSTGRES_*` values when the `postgres_data` volume is first initialized.

Use `SESSION_COOKIE_SECURE=true` only when the app is served through HTTPS. For plain local `$HUMAN_BRAIN_URL`, keep it `false` or browser login cookies may not work.

3. Start PostgreSQL, Redis, and the app:

```bash
docker compose up --build -d
```

4. Apply database migrations:

```bash
docker compose exec web flask --app manage:app db upgrade
```

5. Create demo access data:

```bash
docker compose exec web python manage.py seed-demo-data
```

Copy the printed demo API key immediately.

6. Open the app:

```text
$HUMAN_BRAIN_URL
```

7. Check service logs:

```bash
docker compose logs -f web
docker compose logs -f postgres
docker compose logs -f celery-worker
```

8. Create optional sample data:

```bash
docker compose exec web flask --app manage:app seed-sample-data --count 100
```

9. Remove optional sample data:

```bash
docker compose exec web flask --app manage:app purge-sample-data
```

10. Back up the Docker PostgreSQL database:

Create the local backup folder first if needed:

```bash
mkdir -p backups
```

```bash
docker compose exec postgres pg_dump -U human_brain human_brain > backups/human_brain.sql
```

Restore a SQL backup into the Docker PostgreSQL database:

```bash
docker compose exec -T postgres psql -U human_brain human_brain < backups/human_brain.sql
```

### Option B: Native PostgreSQL Plus Systemd

Use this path when PostgreSQL and Redis run directly on the Linux host and the web app runs as a systemd service.

1. Install OS packages on Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip postgresql postgresql-contrib redis-server build-essential libgl1 libglib2.0-0
```

2. Enable PostgreSQL and Redis:

```bash
sudo systemctl enable --now postgresql
sudo systemctl enable --now redis-server
```

3. Create the PostgreSQL role and database:

```bash
sudo -u postgres psql
```

Inside the `psql` prompt:

```sql
CREATE USER human_brain WITH PASSWORD 'change-this-password';
CREATE DATABASE human_brain OWNER human_brain;
GRANT ALL PRIVILEGES ON DATABASE human_brain TO human_brain;
\q
```

4. Verify local database login:

```bash
psql "postgresql://human_brain:change-this-password@localhost:5432/human_brain" -c "select version();"
```

If this fails, fix PostgreSQL authentication before continuing.

5. Prepare the application checkout:

```bash
cd human-brain
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-core.txt
```

Optional ML and vision dependencies:

```bash
pip install -r requirements-ml.txt
```

6. Create `.env` for native PostgreSQL:

```bash
cp .env.example .env
```

Edit `.env`:

```env
FLASK_ENV=production
SECRET_KEY=replace-this-with-a-long-random-secret
DATABASE_URL=postgresql+psycopg://human_brain:change-this-password@localhost:5432/human_brain
REDIS_URL=redis://localhost:6379/2
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
RATELIMIT_STORAGE_URI=redis://localhost:6379/3
SESSION_COOKIE_SECURE=false
CORS_ENABLED=false
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
VECTOR_STARTUP_WARMUP=true
VECTOR_AUTO_REPAIR_ON_WARMUP=true
FAISS_INDEX_DIR=faiss_indexes
SNAPSHOT_DIR=uploads/snapshots
LOG_LEVEL=INFO
```

Use a strong unique `SECRET_KEY` and database password. If you put the app behind HTTPS, change `SESSION_COOKIE_SECURE=true`.

7. Create runtime directories:

```bash
mkdir -p faiss_indexes uploads/snapshots uploads/memory_uploads logs backups
```

8. Apply migrations:

```bash
flask --app manage:app db upgrade
```

9. Create initial demo workspace, agent, and API key:

```bash
python manage.py seed-demo-data
```

Copy the printed API key immediately.

10. Test the app manually before installing systemd:

```bash
gunicorn -c gunicorn.conf.py manage:app
```

Open:

```text
$HUMAN_BRAIN_URL
```

Stop Gunicorn with `Ctrl+C` after the test.

11. Install the systemd service:

```bash
scripts/install_systemd.sh --skip-deps --skip-migrations
```

The installer asks for your `sudo` password, writes `/etc/systemd/system/human-brain.service`, reloads systemd, enables the service, and starts it.

12. Check the running service:

```bash
sudo systemctl status human-brain
sudo journalctl -u human-brain -f
```

13. Re-run migrations after pulling updates:

```bash
source .venv/bin/activate
flask --app manage:app db upgrade
sudo systemctl restart human-brain
```

14. Rebuild FAISS and correlations after large imports or upgrades:

```bash
source .venv/bin/activate
flask --app manage:app rebuild-index
flask --app manage:app rebuild-correlations
```

15. Back up native PostgreSQL:

```bash
pg_dump "postgresql://human_brain:change-this-password@localhost:5432/human_brain" > backups/human_brain.sql
```

Restore native PostgreSQL:

```bash
psql "postgresql://human_brain:change-this-password@localhost:5432/human_brain" < backups/human_brain.sql
```

16. Common checks:

```bash
psql "postgresql://human_brain:change-this-password@localhost:5432/human_brain" -c "\dt"
redis-cli ping
curl "$HUMAN_BRAIN_URL/login"
```

Expected results:

- `psql \dt` lists application tables after migrations.
- `redis-cli ping` returns `PONG`.
- `curl` returns the login page HTML or a redirect.

## Systemd Install

For a Linux host with systemd, create and review `.env`, then run the installer:

```bash
cp .env.example .env
$EDITOR .env
scripts/install_systemd.sh
```

The installer creates `.venv`, installs `requirements-core.txt`, runs database migrations, asks for your `sudo` password before writing the unit, and installs `human-brain.service` under `/etc/systemd/system/`.

Useful commands:

```bash
sudo systemctl status human-brain
sudo journalctl -u human-brain -f
sudo systemctl restart human-brain
```

Common options:

```bash
scripts/install_systemd.sh --port 5000 --workers 3 --threads 2
scripts/install_systemd.sh --service-name human-brain-dev --no-start
scripts/install_systemd.sh --skip-deps --skip-migrations
```

## Settings Page

Operational settings are managed in the UI at `/settings`:

- Local-first privacy mode
- Auto-store consolidated memories
- Memory Firewall for high/secret sensitivity context injection
- Active embedding model and allowed embedding model list
- Ollama base URL for local embedding models
- Camera enablement
- Snapshot storage
- Vision auto-save
- Active vision model
- Available vision model registry
- Retention days

Environment variables are for secrets, deployment defaults, database/Redis URLs, and filesystem paths.

Set **Public base URL** in Settings, or `HUMAN_BRAIN_URL` in `.env`, to the externally reachable reverse-proxy URL. Tokenized uploaded file/image links use this value, for example `https://human-brain.ibnet.lan/memory-assets/...`, instead of the internal Gunicorn host.

## API Authentication

Agents authenticate with:

```http
X-API-Key: hb_...
```

API keys are hashed in the database. Raw keys are only shown at creation.

## Agent API Example

After `python manage.py seed-demo-data`, copy the printed demo API key.

Set the app URL once before running the examples:

```bash
export HUMAN_BRAIN_URL=http://localhost:5000
export HUMAN_BRAIN_API_KEY=hb_REPLACE_ME
export HUMAN_BRAIN_WORKSPACE_ID=1
```

Store memory:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/add" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d '{
    "agent_id": 1,
    "workspace_id": 1,
    "title": "Deployment choice",
    "content": "The project uses PostgreSQL in production and SQLite only for local development.",
    "memory_type": "technical_notes",
    "tags": ["deployment", "database"],
    "importance_score": 0.8,
    "trust_score": 0.9,
    "confirmed": true
  }'
```

Upload a document as one memory:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/upload" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -F "workspace_id=$HUMAN_BRAIN_WORKSPACE_ID" \
  -F "title=Reference document" \
  -F "memory_type=technical_notes" \
  -F "tags=reference,upload" \
  -F "confirmed=true" \
  -F "ingest_mode=full" \
  -F "uploads=@/path/to/reference.pdf"
```

Upload a long document as searchable chunks:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/upload" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -F "workspace_id=$HUMAN_BRAIN_WORKSPACE_ID" \
  -F "title=Long project report" \
  -F "memory_type=project" \
  -F "tags=project,report" \
  -F "confirmed=true" \
  -F "ingest_mode=chunks" \
  -F "chunk_size=4000" \
  -F "uploads=@/path/to/report.docx"
```

Upload an image as a vision memory:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/upload" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -F "workspace_id=$HUMAN_BRAIN_WORKSPACE_ID" \
  -F "title=Profile image" \
  -F "memory_type=vision" \
  -F "tags=profile,image" \
  -F "confirmed=true" \
  -F "uploads=@/path/to/profile.jpg"
```

`/api/v1/memory/upload` accepts multipart form data. Use `uploads` for one or more files, or `file` for a single file. Documents support `ingest_mode=full` for one memory per file and `ingest_mode=chunks` for one memory per extracted text chunk. Uploaded assets are returned in `memory.assets[]` with tokenized `url` values.

Agent search responses include uploaded asset links. If an agent needs to show a previously uploaded image or document, it should search memory and use `assets[].url`.

Replace the actual file behind an uploaded document or image memory:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/123/asset/replace" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -F "title=Updated reference document" \
  -F "file=@/path/to/replacement.pdf"
```

Asset replacement keeps the memory ID and tokenized asset URL stable, replaces the stored file, refreshes extracted document text or image metadata, refreshes vectors, and reruns correlations. Chunked document replacement updates one existing memory; upload a new chunked document when the chunk boundaries need to change.

Create and consolidate a session:

```bash
SESSION_ID=$(curl -s -X POST "$HUMAN_BRAIN_URL/api/v1/session/start" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d '{"agent_id":1,"workspace_id":1,"title":"Planning"}' | python -c 'import sys,json; print(json.load(sys.stdin)["session_id"])')

curl -X POST "$HUMAN_BRAIN_URL/api/v1/session/add-message" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d "{\"session_id\":$SESSION_ID,\"role\":\"user\",\"content\":\"Decision: use Redis as the Celery broker. Task: rebuild FAISS nightly.\"}"

curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/search" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d "{\"workspace_id\":$HUMAN_BRAIN_WORKSPACE_ID,\"session_id\":$SESSION_ID,\"query\":\"deployment status\",\"top_k\":8}"

curl -X POST "$HUMAN_BRAIN_URL/api/v1/session/consolidate" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d "{\"session_id\":$SESSION_ID}"
```

Starting a session creates the session row. The session fills when the agent calls `/api/v1/session/add-message` or includes the numeric `session_id` on related agent API calls while session auto-capture is enabled in Settings.

Inspect background jobs created by session consolidation:

```bash
curl "$HUMAN_BRAIN_URL/api/v1/jobs?workspace_id=$HUMAN_BRAIN_WORKSPACE_ID" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

Retrieve context for an AI agent:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/context/build" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d '{
    "agent_id": 1,
    "workspace_id": 1,
    "prompt": "How should I deploy the memory system?",
    "session_id": 1,
    "top_k": 8,
    "memory_types": ["technical_notes", "decisions", "tasks"],
    "max_tokens": 1200,
    "sensitivity_policy": "strict"
  }'
```

## Semantic Vector Search

Human-Brain uses FAISS as the primary retrieval path for semantic memory search. Metadata stays in PostgreSQL or SQLite; FAISS stores only vectors.

Search flow:

1. The query is embedded with the same configured `EMBEDDING_MODEL` used for stored memories.
2. The query vector is normalized.
3. The workspace FAISS index is searched with expanded `top_k`.
4. FAISS returns stable `vector_id` values from `IndexIDMap2`.
5. `memory_vectors` maps `vector_id` back to `memory_id`, `workspace_id`, model name, dimension, hashes, and index name.
6. The database applies workspace, agent, archive/delete, sensitivity, and type filters.
7. Results return `semantic_score`, `vector_score`, `vector.vector_id`, `vector.embedding_model`, `vector.vector_dim`, `vector.raw_score`, and timing.

Scoring is intentionally vector-first:

```text
overall_score =
  semantic_score * 0.60 +
  keyword_score  * 0.15 +
  trust_score    * 0.10 +
  importance     * 0.10 +
  recency_score  * 0.05
```

Keyword search is used as a fallback only when FAISS returns no valid semantic candidates. This prevents keyword overlap and old correlations from dominating agent context.

After upgrading an existing installation, run:

```bash
flask --app manage:app db upgrade
python manage.py rebuild-index
python manage.py vector-health
python manage.py test-search "where can I find unixfor online"
```

The search response includes timing:

```json
{
  "timing": {
    "embedding_ms": 3.21,
    "faiss_load_ms": 0.03,
    "faiss_search_ms": 0.12,
    "vector_map_ms": 0.18,
    "db_lookup_ms": 2.14,
    "correlation_ms": 0,
    "rerank_ms": 0.09,
    "serialization_ms": 0.42,
    "total_ms": 6.31,
    "elapsed_ms": 6.31,
    "result_count": 3,
    "semantic": true,
    "mode": "agent"
  }
}
```

For fast agent retrieval, use compact GET search:

```bash
curl "$HUMAN_BRAIN_URL/api/v1/search?workspace_id=1&query=where%20can%20I%20find%20unixfor%20online&mode=agent&compact=true" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

Compact mode returns only the fields an agent needs:

```json
{
  "memory_id": 106,
  "title": "Unixfor Company Information - chunk 2",
  "content": "For more detailed information...",
  "semantic_score": 0.8383,
  "vector_score": 0.8383,
  "trust_score": 0.5
}
```

Search modes:

- `mode=agent`: compact agent payload; no assets, correlations, hashes, audit fields, or timestamps unless explicitly requested.
- `mode=ui`: normal UI payload.
- `mode=debug`: full payload with vectors and correlations.

Warm caches after deployment or rebuild:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/vector/warmup" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

Optional startup warmup:

```env
VECTOR_STARTUP_WARMUP=true
VECTOR_AUTO_REPAIR_ON_WARMUP=true
```

Vector diagnostics:

```bash
curl "$HUMAN_BRAIN_URL/api/v1/vector/health" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

The endpoint reports loaded indexes, embedding model, vector dimension, FAISS index type, total vectors, orphan database vectors, missing FAISS vectors, memories without vectors, and last rebuild time.

Performance diagnostics:

```bash
curl "$HUMAN_BRAIN_URL/api/v1/performance" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

Run local benchmarks:

```bash
python manage.py benchmark-search "where can I find unixfor online" --queries 100
python manage.py benchmark-search "where can I find unixfor online" --queries 1000
python manage.py benchmark-search "where can I find unixfor online" --queries 5000
```

The benchmark outputs average latency, p95, p99, and queries per second.

## Production Notes

- Set a strong `SECRET_KEY`.
- Use PostgreSQL and Redis.
- Keep `CORS_ENABLED=false` unless a trusted integration requires it.
- Terminate HTTPS at nginx or another reverse proxy, and set `SESSION_COOKIE_SECURE=true`.
- Run `gunicorn -c gunicorn.conf.py manage:app`.
- Run workers with `celery -A manage.celery worker --loglevel=INFO`.
- Never log raw API keys, passwords, or tokens.

## Self-Signed HTTPS Certificate

For an internal LAN deployment such as `https://human-brain.ibnet.lan`, use a local CA and sign the nginx server certificate with it. Trust the CA certificate on clients and agent hosts.

Create a local CA:

```bash
sudo mkdir -p /etc/nginx/ssl/ibnet
cd /etc/nginx/ssl/ibnet

sudo openssl genrsa -out ibnet-ca.key 4096
sudo openssl req -x509 -new -nodes -key ibnet-ca.key -sha256 -days 3650 \
  -out ibnet-ca.crt \
  -subj "/CN=IBNET Local CA"
```

Create the server certificate request with Subject Alternative Names:

```bash
sudo tee human-brain-san.cnf >/dev/null <<'EOF'
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = req_ext

[dn]
CN = human-brain.ibnet.lan

[req_ext]
subjectAltName = @alt_names

[alt_names]
DNS.1 = human-brain.ibnet.lan
DNS.2 = localhost
IP.1 = 127.0.0.1
EOF

sudo openssl genrsa -out ibnet.key 2048
sudo openssl req -new -key ibnet.key -out ibnet.csr -config human-brain-san.cnf
```

Sign the server certificate:

```bash
sudo openssl x509 -req -in ibnet.csr \
  -CA ibnet-ca.crt -CAkey ibnet-ca.key -CAcreateserial \
  -out ibnet.crt -days 825 -sha256 \
  -extensions req_ext -extfile human-brain-san.cnf
```

Use the server certificate and key in nginx:

```nginx
server {
    listen 443 ssl;
    server_name human-brain.ibnet.lan;

    ssl_certificate     /etc/nginx/ssl/ibnet/ibnet.crt;
    ssl_certificate_key /etc/nginx/ssl/ibnet/ibnet.key;

    location / {
        proxy_pass http://127.0.0.1:5680;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

Trust the CA on Ubuntu/Debian clients and agent hosts:

```bash
sudo cp /etc/nginx/ssl/ibnet/ibnet-ca.crt /usr/local/share/ca-certificates/ibnet-ca.crt
sudo update-ca-certificates
```

Agent runtime trust options:

```bash
export REQUESTS_CA_BUNDLE=/etc/nginx/ssl/ibnet/ibnet-ca.crt
export NODE_EXTRA_CA_CERTS=/etc/nginx/ssl/ibnet/ibnet-ca.crt
```

Test:

```bash
curl https://human-brain.ibnet.lan/login
curl --cacert /etc/nginx/ssl/ibnet/ibnet-ca.crt https://human-brain.ibnet.lan/login
```

Set the public URL so generated asset links use the external HTTPS host:

```env
HUMAN_BRAIN_URL=https://human-brain.ibnet.lan
SESSION_COOKIE_SECURE=true
```

Do not copy or share `ibnet.key` or `ibnet-ca.key`; they are private keys.

## PostgreSQL, Redis, Celery Production Setup

Use PostgreSQL for production data and Redis for Celery.

```env
DATABASE_URL=postgresql+psycopg://human_brain:password@localhost:5432/human_brain
REDIS_URL=redis://localhost:6379/2
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
SESSION_COOKIE_SECURE=true
CORS_ENABLED=false
```

Install and migrate:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-core.txt
pip install -r requirements-ml.txt
flask --app manage:app db upgrade
```

Run web:

```bash
gunicorn -c gunicorn.conf.py manage:app
```

Run workers:

```bash
celery -A manage.celery worker --loglevel=INFO
celery -A manage.celery beat --loglevel=INFO
```

See `docs/AGENT_API_PROTOCOL.md` for the complete agent retrieval and correlation protocol.

## Backup and Restore

SQLite development:

```bash
python manage.py backup
python manage.py restore backups/human_brain_YYYYMMDDHHMMSS.sqlite3
```

PostgreSQL production:

```bash
pg_dump "$DATABASE_URL" > backups/human_brain.sql
psql "$DATABASE_URL" < backups/human_brain.sql
```

The Backups page can create, download, restore, and delete local backup archives.

## Agent Logs And Jobs

Settings can enable rotated JSONL agent API logging. Logs are stored under `logs/agent_api/` and are visible in the Agent Logs page with pagination, search, and detail modals. Each entry records the API path, method, agent id, request payload or uploaded filenames, response payload, and status.

Dashboard Jobs are background worker records for operations such as session consolidation. Agents can inspect their jobs with `/api/v1/jobs`; operators can use the dashboard to monitor queued, running, completed, and failed jobs.

Settings can also enable scheduled duplicate consolidation. The worker finds duplicate/similar memories, creates one consolidated memory, and optionally archives the duplicate source memories.

## YOLO Setup

Vision settings are controlled in `/settings`. Add model names or local paths to the available model list, set the active model, enable camera access, and decide whether snapshots are allowed. Metadata is stored by default; frames are not persisted unless snapshot storage is enabled.

Check camera indexes:

```bash
flask --app manage:app camera-check --max-index 5
```

## Troubleshooting

- Missing FAISS index: run `python manage.py rebuild-index`.
- Search shows `semantic_score=0` or `vector_id=null`: run `flask --app manage:app db upgrade`, then `python manage.py rebuild-index`, then check `python manage.py vector-health`.
- Search returns no results while `faiss_hits` is nonzero: the workspace index may be stale. Keep `VECTOR_AUTO_REPAIR_ON_WARMUP=true`, restart the app, or run `python manage.py rebuild-index`.
- Bad or outdated correlation edges: run `flask --app manage:app rebuild-correlations`.
- Celery jobs stuck: confirm Redis is reachable and workers are running.
- Vision disabled: enable camera use on Settings.
- PostgreSQL migrations: run `flask --app manage:app db migrate` and `flask --app manage:app db upgrade`.
