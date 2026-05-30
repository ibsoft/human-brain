from app.extensions import db
from app.models import Memory
from app.services.memory_service import MemoryService
from app.services.settings_service import SettingsService


class ContextService:
    def build(self, payload):
        firewall = SettingsService.get("sensitivity_firewall", {})
        blocked = {"secret"} if firewall.get("block_secret", True) else set()
        if firewall.get("block_high", True):
            blocked.add("high")

        search_payload = {
            "workspace_id": payload["workspace_id"],
            "agent_id": payload["agent_id"],
            "query": payload["prompt"],
            "top_k": int(payload.get("top_k", 8)),
            "memory_types": payload.get("memory_types"),
            "min_trust": payload.get("min_trust", 0.0),
            "include_correlations": bool(payload.get("include_correlations")),
            "correlation_limit": int(payload.get("correlation_limit", 3)),
        }
        results = MemoryService().search(search_payload, semantic=True)
        max_tokens = int(payload.get("max_tokens", 1200))
        context_lines = []
        used = []
        token_budget = 0
        for result in results:
            memory = result["memory"]
            if memory["sensitivity_level"] in blocked and payload.get("sensitivity_policy", "strict") == "strict":
                continue
            line = f"- [{memory['memory_type']} trust={memory['trust_score']:.2f}] {memory['summary'] or memory['content']}"
            approx_tokens = max(len(line) // 4, 1)
            if token_budget + approx_tokens > max_tokens:
                break
            token_budget += approx_tokens
            context_lines.append(line)
            if payload.get("include_correlations"):
                for correlation in result.get("correlations", []):
                    related = correlation["related_memory"]
                    if related["sensitivity_level"] in blocked and payload.get("sensitivity_policy", "strict") == "strict":
                        continue
                    context_lines.append(
                        f"  - correlated [{correlation['strength']:.2f}] {related['title']}: {related['summary'] or related['content']}"
                    )
            used.append(
                {
                    "id": memory["id"],
                    "score": result["relevance_score"],
                    "vector_score": result.get("vector_score", 0.0),
                    "reason": result["explanation"],
                    "correlations": result.get("correlations", []),
                }
            )

        return {
            "context": "\n".join(context_lines),
            "memories": used,
            "policy": {
                "sensitivity_policy": payload.get("sensitivity_policy", "strict"),
                "blocked_levels": sorted(blocked),
                "max_tokens": max_tokens,
            },
        }


def confirm_memory(memory_id):
    memory = db.session.get(Memory, memory_id)
    if memory:
        memory.confirmed = True
        memory.pending_approval = False
        db.session.commit()
    return memory
