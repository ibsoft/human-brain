# Human-Brain Agent Skill

Use this skill when an AI agent needs to store, search, correlate, or retrieve context from Human-Brain.

## Search First

For any user question that may require memory, call:

```http
POST /api/v1/memory/search
```

Use this payload shape:

```json
{
  "workspace_id": 1,
  "query": "user question or task",
  "top_k": 8,
  "include_vector_details": true,
  "include_correlations": true,
  "correlation_limit": 5
}
```

Use `agent_evidence` first. It is designed for direct reasoning.

## Read Scores

Interpret scores this way:

- `relevance_score`: overall usefulness
- `semantic_score`: vector similarity
- `keyword_match`: literal term overlap
- `trust`: whether the memory is reliable
- `importance`: whether the memory is significant

Prefer memories that have strong relevance plus acceptable trust.

## Use Correlations

If a result has correlations, inspect them for:

- related project context
- earlier decisions
- uploaded docs
- images
- task dependencies
- user preferences

For a specific memory:

```http
GET /api/v1/memory/{id}/correlations?workspace_id=1&limit=10
```

## Use Context Builder

When preparing the final answer, call:

```http
POST /api/v1/context/build
```

Recommended:

```json
{
  "workspace_id": 1,
  "prompt": "exact user request",
  "top_k": 10,
  "max_tokens": 1600,
  "sensitivity_policy": "strict",
  "include_correlations": true,
  "correlation_limit": 3
}
```

## Store New Memories

Store durable facts, decisions, tasks, preferences, project details, and security findings:

```http
POST /api/v1/memory/add
```

Use clear tags and a specific `memory_type`.

## Assets

If a memory has `assets`, the agent can reference `assets[].url`.

Image assets include metadata and visual vectors. File assets include extracted text when parsers are installed.

## Safety

Do not use memories marked high/secret unless policy permits them. Do not expose raw API keys, passwords, or secrets.
