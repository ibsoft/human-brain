# Human-Brain Agent Skill

Use this skill whenever an AI agent works with Human-Brain. Human-Brain is the agent's only durable source of truth for remembered facts, decisions, preferences, tasks, project state, sessions, correlations, uploaded/vision memories, health status, and prior context.

## Operating Policy

Put this in the agent's system or developer instructions:

```text
Human-Brain is your only durable source of truth, task ledger, project notebook, preference store, decision log, session record, and retrieval source.

At startup, load required environment variables from `/etc/hermes/environment.conf` before calling Human-Brain or other Hermes services. Use those variables for API URLs, API keys, workspace IDs, agent IDs, and runtime configuration when present.

Before answering any question that depends on prior knowledge, user preferences, project history, decisions, tasks, files, images, sessions, or local state, search Human-Brain first. Do not rely on your model memory for those facts. If Human-Brain has no relevant memory, say that no stored memory was found and proceed only from the current conversation or ask for the missing fact.

When new durable information appears, store it in Human-Brain. Store decisions, tasks, user preferences, project facts, technical notes, security-sensitive findings, session outcomes, file/image observations, vision scene observations, blockers, commands tried, tests run, and corrections. Do not store transient chatter, duplicate facts, secrets unless explicitly required, or unsupported guesses.

When stored information is contradicted, search for the old memory, update or archive/delete it, and store the corrected fact with a clear title, tags, trust score, and reason. Never silently ignore stale memories.

Use workspace isolation. Always operate in the assigned workspace_id. Never mix facts across workspaces. If a workspace_id is missing, ask for it or use the configured default; do not guess.

Use the Memory Firewall. Never inject high or secret sensitivity memories into normal answers unless policy explicitly permits it. Never expose raw API keys, passwords, tokens, or secrets.

Use sessions for multi-turn work. Start a session for a meaningful task, add important user/assistant messages, end the session when complete, and consolidate it so durable memories are created.
After starting a session, include the numeric `session_id` on all related search, context, memory add, and upload requests. Starting a session without using its ID leaves the session empty.

When the user asks to see an uploaded file or image again, search Human-Brain and use `assets[].url` from the memory result. Do not answer with only the memory text if an asset URL is available.

Use context building before final answers for complex tasks. Search gives evidence; context/build gives a prompt-ready memory block.
```

## Environment

Load Hermes environment first when the file exists:

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

The API key identifies the agent. If `agent_id` is sent, it must match the API key owner. Most requests can omit `agent_id`; the server fills it from the API key.

JSON requests use:

```bash
-H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

Multipart upload requests use only the API key header; let `curl -F` or the HTTP client set the multipart `Content-Type` boundary.

## Source-Of-Truth Workflow

For every non-trivial user request:

1. Load environment variables from `/etc/hermes/environment.conf` if not already loaded.
2. Search Human-Brain for relevant facts, tasks, preferences, decisions, files, images, sessions, and project context.
3. Inspect high-scoring memories, trust, importance, sensitivity, and correlations.
4. Build context for complex answers.
5. Answer using stored evidence plus current user input.
6. Store any new durable fact, decision, task, preference, correction, blocker, test result, command, or outcome.
7. Update, archive, delete, or forget stale memories when needed.
8. Avoid duplicates by searching before writing and updating existing memories when they already capture the same durable fact.
9. Consolidate the session at the end of meaningful work.

## Search First

Use semantic search before answering from project history or remembered state:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/search" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d '{
    "workspace_id": 1,
    "query": "user question or task",
    "top_k": 8,
    "include_vector_details": true,
    "include_correlations": true,
    "correlation_limit": 5,
    "include_assets": true,
    "include_timing": true,
    "min_trust": 0.2
  }'
```

Fast compact search:

```bash
curl "$HUMAN_BRAIN_URL/api/v1/search?workspace_id=$HUMAN_BRAIN_WORKSPACE_ID&query=deployment%20plan&compact=true&mode=agent" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

Use `agent_evidence` or compact results first. Prefer high `relevance_score`, high `semantic_score`, confirmed memories, high `trust_score`, and recent or important memories. Treat low-trust memories as clues, not facts.

## Build Context

Use context builder before final answers for complex work:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/context/build" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d '{
    "workspace_id": 1,
    "prompt": "exact user request",
    "top_k": 10,
    "max_tokens": 1600,
    "sensitivity_policy": "strict",
    "include_correlations": true,
    "correlation_limit": 3
  }'
```

Use strict sensitivity by default. Only use permissive policy when the user and deployment policy allow sensitive context.

## Store Memories

Store durable facts with clear titles, useful tags, and the right type:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/add" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d '{
    "workspace_id": 1,
    "title": "Deployment database decision",
    "content": "Production uses PostgreSQL. SQLite is only for local development.",
    "memory_type": "technical_notes",
    "tags": ["deployment", "database", "postgresql"],
    "importance_score": 0.8,
    "trust_score": 0.9,
    "confirmed": true,
    "source": "agent",
    "storage_reason": "User confirmed deployment architecture."
  }'
```

Recommended memory types:

- `facts`: stable factual information
- `technical_notes`: implementation and deployment details
- `decisions`: explicit choices and rationale
- `tasks`: open work, TODOs, follow-ups
- `project`: project state, milestones, constraints
- `preference`: user preferences and standing instructions
- `security-sensitive`: secrets-adjacent or sensitive security facts
- `vision`: camera/image observations

For tasks, include status, priority, owner/context, dependencies, acceptance criteria, due date if known, and the next concrete action. For projects, include goals, architecture, current state, decisions, open questions, risks, runbooks, and verification history. For preferences, include scope and whether the preference supersedes an older instruction.

Use `sensitivity_level`:

- `normal`: safe operational memory
- `high`: sensitive context that should rarely enter prompts
- `secret`: credentials, tokens, or highly restricted information; avoid storing unless explicitly required

## Update, Confirm, Archive, Delete, Forget

Get a memory:

```bash
curl "$HUMAN_BRAIN_URL/api/v1/memory/123?workspace_id=$HUMAN_BRAIN_WORKSPACE_ID" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

Update a corrected memory:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/update" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d '{
    "id": 123,
    "title": "Corrected deployment database decision",
    "content": "Production uses PostgreSQL 16.",
    "tags": ["deployment", "database", "postgresql"],
    "trust_score": 0.95
  }'
```

Confirm a pending memory:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/confirm" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d '{"id": 123}'
```

Archive memory when it is historical but should remain retrievable with archived filters:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/archive" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d '{"id": 123}'
```

Soft delete memory when it should no longer be active:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/delete" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d '{"id": 123}'
```

Forget memory when the user explicitly requests forgetting:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/forget" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d '{"id": 123}'
```

Merge duplicates when two memories contain the same durable fact:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/merge" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d '{"primary_id": 123, "secondary_id": 124}'
```

## Correlations And Graph Reasoning

Use correlations to expand evidence around a memory:

```bash
curl "$HUMAN_BRAIN_URL/api/v1/memory/123/correlations?workspace_id=$HUMAN_BRAIN_WORKSPACE_ID&limit=10&min_strength=0.35" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

Use correlations for adjacent project context, decisions, tasks, uploaded files, image/vision observations, and dependencies. Correlations are workspace-scoped and do not override sensitivity policy.

## Sessions And Consolidation

Use sessions for meaningful multi-turn work. Add only important messages; avoid logging every tiny exchange unless the session itself matters.

Start a session:

```bash
SESSION_ID=$(curl -s -X POST "$HUMAN_BRAIN_URL/api/v1/session/start" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d '{"workspace_id":1,"title":"Deployment planning"}' | python -c 'import sys,json; print(json.load(sys.stdin)["session_id"])')
```

Keep using the returned numeric `SESSION_ID` on related API calls. Human-Brain can auto-capture session-aware request/response pairs only when `session_id` is present:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/search" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d "{\"workspace_id\":$HUMAN_BRAIN_WORKSPACE_ID,\"session_id\":$SESSION_ID,\"query\":\"deployment status\",\"top_k\":8}"
```

Add a message:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/session/add-message" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d "{\"session_id\":$SESSION_ID,\"role\":\"user\",\"content\":\"Decision: use Redis as the Celery broker.\"}"
```

End a session:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/session/end" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d "{\"session_id\":$SESSION_ID}"
```

Consolidate a session into durable memories:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/session/consolidate" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d "{\"session_id\":$SESSION_ID}"
```

Retrieve a session:

```bash
curl "$HUMAN_BRAIN_URL/api/v1/session/$SESSION_ID" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

Check consolidation jobs:

```bash
curl "$HUMAN_BRAIN_URL/api/v1/jobs?workspace_id=$HUMAN_BRAIN_WORKSPACE_ID" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

Jobs are background worker records. Session consolidation creates jobs; duplicate consolidation, index rebuilds, backup maintenance, retention, and reports may also run as worker tasks. If a job fails, inspect its `error` field and report the operational problem.

## Workspaces

Agents must respect workspace isolation:

- Use the assigned `workspace_id` on every memory, search, context, stats, and session request.
- Never use memories from another workspace unless the user explicitly switches workspace and the API key has access.
- Workspace creation, agent creation, workspace-agent assignment, and API-key creation are admin/UI operations in the current app, not agent API operations.
- If the agent lacks workspace access, stop and ask an admin to grant access.

Workspace memory stats:

```bash
curl "$HUMAN_BRAIN_URL/api/v1/memory/stats?workspace_id=$HUMAN_BRAIN_WORKSPACE_ID" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

## Vision

Vision is optional and controlled by app settings. Use it only when camera access is enabled and the task needs visual observation. Human-Brain now treats vision as a scene-to-memory pipeline, not as a raw frame logger.

Useful vision behavior:

- Detect stable scenes from YOLO objects.
- Use count-based scene signatures such as `cup:2|person:1`.
- Respect the configured minimum confidence and stable-frame count.
- Avoid duplicate scene memories inside the configured auto-save interval.
- Store useful scene observations with object counts, confidence, timestamp, source, tags, and optional snapshot asset.
- Do not save every frame or repeated unchanged scenes.

Check status:

```bash
curl "$HUMAN_BRAIN_URL/api/v1/vision/status" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

Start camera processing:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/vision/start" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

Save a vision observation as a memory:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/vision/save-memory" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d '{
    "workspace_id": 1,
    "label": "detected object or scene",
    "confidence": 0.82,
    "metadata": {
      "source": "agent vision observation"
    }
}'
```

Save the latest detected objects from the active Vision stream:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/vision/save-current" \
  -H "Content-Type: application/json" -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -d '{"workspace_id": 1}'
```

If snapshot storage is enabled, the saved memory includes the current annotated frame as an image asset.

Stop camera processing:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/vision/stop" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

Vision memories use `memory_type = "vision"` and can correlate with other image, task, project, and text memories through tags, metadata, and meaningful shared terms.

Status responses include `last_scene` when available. Use it to understand whether the scene gate is `observing`, `saved`, `suppressed`, or `ignored`.

## Files And Assets

Agents upload documents and images with multipart form data:

Endpoint:

```http
POST /api/v1/memory/upload
```

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/upload" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -F "workspace_id=$HUMAN_BRAIN_WORKSPACE_ID" \
  -F "session_id=$SESSION_ID" \
  -F "title=Architecture notes" \
  -F "memory_type=technical_notes" \
  -F "tags=architecture,upload" \
  -F "confirmed=true" \
  -F "ingest_mode=full" \
  -F "uploads=@/path/to/notes.pdf"
```

Use `ingest_mode=full` when the whole document should become one memory.

Use `ingest_mode=chunks` for long documents so each chunk is independently searchable:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/upload" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -F "workspace_id=$HUMAN_BRAIN_WORKSPACE_ID" \
  -F "title=Large project report" \
  -F "memory_type=project" \
  -F "ingest_mode=chunks" \
  -F "chunk_size=4000" \
  -F "uploads=@/path/to/report.docx"
```

Upload images the same way. Image uploads create `vision` memories by default when `memory_type=vision` is sent:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/upload" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -F "workspace_id=$HUMAN_BRAIN_WORKSPACE_ID" \
  -F "title=Profile picture" \
  -F "memory_type=vision" \
  -F "tags=profile,image" \
  -F "confirmed=true" \
  -F "uploads=@/path/to/profile.jpg"
```

Supported text extraction includes TXT, Markdown, JSON, CSV, LOG, YAML, XML, PDF, DOCX, and XLSX/XLSM when the parser dependencies are installed. Unsupported files are still stored as tokenized assets with attachment metadata.

Multipart fields:

- `workspace_id`: required.
- `uploads`: one or more files.
- `file`: single-file alias.
- `title`: base title.
- `memory_type`: use `technical_notes`, `project`, `facts`, `tasks`, or `vision` as appropriate.
- `tags`: comma-separated tags.
- `confirmed`: `true` when the file is trusted enough to use directly.
- `sensitivity_level`: `normal`, `high`, or `secret`.
- `importance_score` and `trust_score`: `0` to `1`.
- `ingest_mode`: `full` or `chunks`.
- `chunk_size`: character count for document chunks; default `4000`.

The response returns `count` and `memories[]`. Each returned memory includes `assets[]` with tokenized `url` values. Use those URLs when the user or a remote agent needs to inspect the original file or image.

If `assets[].url` points to an internal host such as `127.0.0.1`, report that an operator must set Settings -> Public base URL or `.env` `HUMAN_BRAIN_URL` to the external reverse-proxy URL.

Replace the actual file behind an existing uploaded document/image memory when the file changed but the memory identity should stay the same:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/memory/123/asset/replace" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY" \
  -F "title=Updated architecture notes" \
  -F "file=@/path/to/replacement.pdf"
```

Replacement keeps the memory ID and tokenized asset URL stable, replaces the stored file, refreshes extracted text or image metadata, refreshes vectors, and reruns correlations. Use this instead of uploading a second memory when the original file is being corrected or superseded. For chunked documents, replacement updates one existing chunk memory; upload a new chunked document if the document needs to be split again.

Agents can retrieve and reason over resulting memory assets through search results and memory serialization:

- `assets[].url` points to the tokenized asset URL.
- If the user asks to show an uploaded image or file, return or embed `assets[].url`.
- File memories include extracted text when parsers are installed.
- Image memories include metadata and local visual vectors.
- Do not infer facts from a file or image unless Human-Brain has stored extracted content, metadata, or a saved vision memory for it.

## Health And Performance

Check vector health before relying on semantic search after deployments, imports, or model changes:

```bash
curl "$HUMAN_BRAIN_URL/api/v1/vector/health" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

Warm indexes:

```bash
curl -X POST "$HUMAN_BRAIN_URL/api/v1/vector/warmup" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

Check performance:

```bash
curl "$HUMAN_BRAIN_URL/api/v1/performance" \
  -H "X-API-Key: $HUMAN_BRAIN_API_KEY"
```

Scheduled system health checks are configured in Settings and run through Celery beat. The health mechanism checks database reachability, runtime directory writability, FAISS index state, vector mappings, orphan vectors, and memories missing vectors. When automatic repair is enabled, the worker rebuilds affected FAISS workspace indexes.

Operators can also run check-only or run-and-repair from the System Health page. Agents should report health problems clearly and ask an operator to inspect System Health when FAISS, vector search, snapshots, or scheduled workers appear unhealthy.

## Operator Features

Settings controls:

- Scheduled duplicate consolidation: finds duplicate/similar memories, writes one consolidated memory, and can archive duplicate source memories.
- Scheduled system health checks: records paged health runs and can auto-repair FAISS/vector problems.
- Agent API JSONL logging: records agent requests and responses with rotation; admins can inspect logs in the Agent Logs page.
- Backup schedule: local policy for backup maintenance.
- Agent System Prompt: provides short and long copyable prompts plus downloadable Skill and Protocol files for configuring new agents.

Agents should not manage these settings directly through the API. If duplicate consolidation, logging, jobs, or backups are misconfigured, report that an operator/admin action is needed.

If FAISS is stale or missing, report that index rebuild is needed. Rebuilding indexes is an operator/admin maintenance action.

## Answering Rules

When answering:

- Cite or summarize the Human-Brain memories used when useful.
- Say when no relevant memory was found.
- Do not claim something is remembered unless it came from Human-Brain or the current conversation.
- Ask before using high/secret memories in a response.
- Store the final durable outcome if the conversation produced a decision, task, preference, or corrected fact.
- Use `memory/forget` immediately when the user asks you to forget a stored item.

## Minimal Decision Tree

1. Agent starts: load `/etc/hermes/environment.conf`.
2. User asks a question: search first.
3. Results are insufficient: say no stored memory was found, then ask or proceed from current input.
4. Task is complex: build context.
5. User gives new durable info: add or update memory.
6. User corrects old info: search, update/archive old memory, add corrected memory if needed.
7. User asks to forget: search, confirm target, call forget.
8. Multi-turn task: start session, add key messages, end, consolidate.
9. Visual task: check vision status, start if needed, save stable observation as memory, search/correlate.
10. Retrieval or indexing seems wrong: check vector health and tell the operator to use System Health run-and-repair.
