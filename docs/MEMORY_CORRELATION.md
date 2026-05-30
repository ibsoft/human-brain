# Memory Correlation

Human-Brain stores memories as isolated records, then adds correlation edges between memories that appear to describe related facts, tasks, sessions, projects, or observations. These edges power the Memory Graph and make it easier to see how an agent's knowledge connects over time.

## What Correlation Does

Correlation creates rows in `memory_correlations`.

Each correlation stores:

- `workspace_id`
- `source_memory_id`
- `target_memory_id`
- `correlation_type`
- `strength`
- `explanation`
- `created_at`

The current correlation type is `related`.

Correlations are workspace-scoped. A memory in Workspace A is never correlated with a memory in Workspace B. This preserves workspace isolation and prevents graph leakage across private projects.

## When Correlation Runs

Correlation runs automatically after a memory is created through `MemoryService.add_memory()`.

Flow:

1. A memory is created.
2. The embedding is generated and stored.
3. The workspace FAISS index is rebuilt.
4. `CorrelationService.correlate_memory(memory)` compares the new memory against recent memories in the same workspace.
5. Strong enough matches are stored in `memory_correlations`.
6. The Memory Graph page renders those edges.

There is also a workspace rebuild method:

```python
CorrelationService().rebuild_workspace(workspace_id)
```

This deletes existing correlations for the workspace and recalculates them from current non-deleted memories.

## Current Scoring Rules

The current implementation is intentionally simple and explainable. It does not yet use embedding vector similarity for correlation strength. It uses deterministic metadata and text overlap rules.

For every new memory, the service looks at up to 250 recent, non-deleted memories in the same workspace.

It calculates a score from:

| Signal | Strength Added | Explanation |
| --- | ---: | --- |
| Shared tags | Up to `0.45` | `0.15` per shared tag, capped |
| Same memory type | `0.20` | Example: both are `task` |
| Same agent | `0.10` | Both memories belong to the same agent |
| Same session | `0.25` | Both came from the same raw session |
| Shared content terms | Up to `0.25` | `0.025` per shared keyword, capped |

The final strength is capped at `1.0`.

Only correlations with strength `>= 0.25` are stored.

## Upload Boilerplate Is Ignored

Uploaded files and images contain operational metadata such as local path, MIME type, stored filename, vector hash, and upload source. These fields are useful for auditability, but they are not meaningful semantic evidence.

Human-Brain ignores generic upload tags and boilerplate terms when building correlations.

Ignored generic tags include:

- `upload`
- `uploaded`
- `file`
- `document`
- `image`
- `visual`
- `pdf`
- `docx`
- `xlsx`
- `txt`
- `log`
- `jpg`
- `jpeg`
- `png`
- `webp`

Ignored boilerplate terms include:

- `stored`
- `path`
- `local`
- `mime`
- `type`
- `bytes`
- `visual`
- `vector`
- `fingerprint`
- `metadata`
- `profile`
- `dominant`
- `color`
- `extractable`
- `requires`
- `original`

This prevents irrelevant correlations such as an astronomy image correlating with an unrelated company PDF only because both were uploaded files.

Image visual vectors are compared only with other compatible image vectors. They are not compared directly against document keyword vectors.

Cross image-document correlation must come from real shared evidence, such as specific shared tags, meaningful shared terms, or useful asset metadata, not upload boilerplate.

## Example

Memory A:

```text
Title: Deployment decision
Type: technical_notes
Tags: deployment, database
Content: Production uses PostgreSQL.
```

Memory B:

```text
Title: Database backup task
Type: task
Tags: deployment, database, backup
Content: Add nightly PostgreSQL backups.
```

Possible score:

- Shared tags: `deployment`, `database` -> `0.30`
- Shared term: `postgresql` -> `0.025`
- Same workspace is required but does not add score

Total: `0.325`

The app stores a `related` correlation with an explanation like:

```text
shared tags: database, deployment, shared terms: postgresql
```

## How Vision Memories Correlate

When vision creates a memory, it is stored like any other memory with:

- `memory_type = "vision"`
- tags such as detected object labels
- text content describing detections, confidence, timestamp, and snapshot metadata if enabled

If the camera sees an apple and the detection is saved as a memory, it can correlate with:

- other `vision` memories
- memories tagged `apple`, `fruit`, `kitchen`, or similar tags
- task/project memories sharing terms such as `apple`
- memories from the same agent/session/workspace

Frames are not automatically stored unless snapshot storage is enabled. Metadata can still correlate.

Example:

An image memory titled `Messier 51` with tags like `m51`, `nebula`, `galaxy`, `astronomy` should not correlate with an unrelated PDF titled `Company Information` just because both contain upload metadata.

It may correlate with:

- another astronomy image with similar visual metadata
- a note tagged `m51` or `nebula`
- a document that actually mentions `Messier 51`
- a project memory about astronomy images

## Duplicate Handling vs Correlation

Duplicate detection and correlation are separate.

Duplicate handling uses `content_hash` and semantic duplicate checks to avoid storing the same memory repeatedly. Repeated duplicate evidence can increase trust.

Correlation does not merge memories. It links related memories while keeping both records intact.

## Privacy and Security Behavior

Correlation follows memory isolation rules:

- Same workspace only.
- Deleted memories are ignored.
- Correlation edges do not bypass Memory Firewall rules.
- Sensitive memories can appear in the graph if the user has access to the page, but context injection still respects `sensitivity_firewall`.

The correlation explanation is safe metadata, but it may mention shared tags or terms. Avoid putting secrets in tags.

## Current Limits

The first version is deliberately explainable and low-risk:

- Correlation does not yet use FAISS semantic similarity.
- It checks only the 250 newest candidate memories.
- It stores only `related` edges.
- It does not yet create separate edge types like `contradicts`, `depends_on`, `caused_by`, or `same_entity`.
- It does not yet perform entity extraction.

## Rebuilding Stored Correlations

Correlation rules only affect new or rebuilt edges. If bad correlations already exist in the database, rebuild them.

All workspaces:

```bash
flask --app manage:app rebuild-correlations
```

One workspace:

```bash
flask --app manage:app rebuild-correlations --workspace-id 1
```

Use this after upgrading correlation rules, changing upload parsing behavior, or importing a large memory batch.

## Recommended Next Improvements

Useful production upgrades:

1. Add semantic similarity as another scoring signal.
2. Add named entity extraction for projects, people, systems, files, URLs, and services.
3. Add explicit edge types: `supports`, `contradicts`, `duplicates`, `depends_on`, `mentions_entity`.
4. Add a UI action to rebuild correlations per workspace.
5. Add correlation audit logs.
6. Add a background job for periodic graph maintenance.
7. Add a threshold setting on the Settings page.

## Source Files

- `app/services/correlation_service.py`
- `app/models/memory.py`
- `app/services/memory_service.py`
- `app/services/document_service.py`
- `app/services/asset_vector_service.py`
- `app/templates/graph.html`
- `app/static/js/app.js`
