import math

from app.extensions import db
from app.models import Memory
from app.services.memory_service import MemoryService, serialize_correlations, serialize_memory
from app.services.settings_service import SettingsService


class ContextService:
    CANDIDATE_LIMIT = 500

    def __init__(self):
        self.memory_service = MemoryService()

    def build(self, payload):
        firewall = SettingsService.get("sensitivity_firewall", {})
        blocked = {"secret"} if firewall.get("block_secret", True) else set()
        if firewall.get("block_high", True):
            blocked.add("high")

        prompt = payload.get("prompt", "")
        prompt_terms = self._query_terms(prompt)
        max_tokens = int(payload.get("max_tokens", 1200))
        top_k = int(payload.get("top_k", 8))
        sensitivity_policy = payload.get("sensitivity_policy", "strict")

        search_results = self._search_candidates(payload, top_k)
        semantic_by_id = {item["memory"]["id"]: item for item in search_results}
        memories = self._workspace_candidates(payload)
        ranked, diagnostics = self._rank_candidates(
            memories=memories,
            semantic_by_id=semantic_by_id,
            prompt_terms=prompt_terms,
            blocked=blocked,
            sensitivity_policy=sensitivity_policy,
            top_k=top_k,
        )

        context_lines = []
        used = []
        token_budget = 0
        for item in ranked:
            memory = item["memory"]
            line = f"- [{memory['memory_type']} trust={memory['trust_score']:.2f}] {memory['summary'] or memory['content']}"
            approx_tokens = max(len(line) // 4, 1)
            if token_budget + approx_tokens > max_tokens:
                break
            token_budget += approx_tokens
            context_lines.append(line)

            correlations = self._result_correlations(memory["id"], payload)
            rendered_correlations = []
            if payload.get("include_correlations"):
                for correlation in correlations:
                    related = correlation["related_memory"]
                    if related["sensitivity_level"] in blocked and sensitivity_policy == "strict":
                        continue
                    if prompt_terms and not self._memory_has_evidence(related, prompt_terms):
                        continue
                    correlation_line = (
                        f"  - correlated [{correlation['strength']:.2f}] {related['title']}: "
                        f"{related['summary'] or related['content']}"
                    )
                    approx_tokens = max(len(correlation_line) // 4, 1)
                    if token_budget + approx_tokens > max_tokens:
                        continue
                    token_budget += approx_tokens
                    context_lines.append(correlation_line)
                    rendered_correlations.append(correlation)

            used.append(
                {
                    "id": memory["id"],
                    "score": item["score"],
                    "vector_score": item["semantic_score"],
                    "reason": item["reason"],
                    "correlations": correlations,
                }
            )

        return {
            "context": "\n".join(context_lines),
            "memories": used,
            "policy": {
                "sensitivity_policy": sensitivity_policy,
                "blocked_levels": sorted(blocked),
                "max_tokens": max_tokens,
                "used_tokens": token_budget,
                "remaining_tokens": max(max_tokens - token_budget, 0),
                "selection": {
                    "mode": diagnostics["mode"],
                    "prompt_terms": sorted(prompt_terms),
                    "search_results": len(search_results),
                    "workspace_candidates": len(memories),
                    "eligible_candidates": diagnostics["eligible_candidates"],
                    "selected_results": len(used),
                },
            },
        }

    def _search_candidates(self, payload, top_k):
        search_payload = {
            "workspace_id": payload["workspace_id"],
            "agent_id": payload["agent_id"],
            "query": payload["prompt"],
            "top_k": max(top_k * 4, 20),
            "query_kind": "context_building",
            "memory_types": payload.get("memory_types"),
            "min_trust": payload.get("min_trust", 0.0),
            "include_correlations": False,
            "filter_agent_id": False,
            "record_access": False,
        }
        results = self.memory_service.search(search_payload, semantic=True)
        return results.get("results", []) if isinstance(results, dict) else results

    def _workspace_candidates(self, payload):
        query = self.memory_service.repo.query_scope(int(payload["workspace_id"]))
        query = self.memory_service._apply_filters(query, {**payload, "filter_agent_id": False})
        return (
            query.order_by(Memory.trust_score.desc(), Memory.importance_score.desc(), Memory.updated_at.desc())
            .limit(self.CANDIDATE_LIMIT)
            .all()
        )

    def _rank_candidates(self, memories, semantic_by_id, prompt_terms, blocked, sensitivity_policy, top_k):
        lexical_model = self._lexical_model(memories, prompt_terms, blocked, sensitivity_policy)
        ranked = []
        rejected = 0
        lexical_available = any(
            self._lexical_score(serialize_memory(memory), lexical_model)[0] > 0
            for memory in memories
            if not (memory.sensitivity_level in blocked and sensitivity_policy == "strict")
        )
        for memory in memories:
            if memory.sensitivity_level in blocked and sensitivity_policy == "strict":
                rejected += 1
                continue
            serialized = serialize_memory(memory)
            lexical_score, matches = self._lexical_score(serialized, lexical_model)
            semantic_result = semantic_by_id.get(memory.id)
            semantic_score = self._semantic_score(semantic_result) if semantic_result else 0.0
            if lexical_available and lexical_score <= 0:
                rejected += 1
                continue
            if prompt_terms and lexical_score <= 0 and semantic_score < 0.78:
                rejected += 1
                continue
            if prompt_terms and lexical_score <= 0 and semantic_score <= 0:
                rejected += 1
                continue
            score = lexical_score * 0.65 + semantic_score * 0.25 + memory.trust_score * 0.06 + memory.importance_score * 0.04
            ranked.append(
                {
                    "memory": serialized,
                    "score": round(score, 4),
                    "semantic_score": round(semantic_score, 4),
                    "reason": {
                        "keyword_match": round(lexical_score, 4),
                        "semantic_similarity": round(semantic_score, 4),
                        "matched_terms": sorted(matches),
                        "importance": memory.importance_score,
                        "trust": memory.trust_score,
                        "access_count": memory.access_count,
                    },
                }
            )
        ranked.sort(key=lambda item: item["score"], reverse=True)
        mode = "ranked"
        if not ranked:
            mode = "empty"
        elif any(item["semantic_score"] > 0 for item in ranked[:top_k]):
            mode = "semantic_and_lexical"
        elif prompt_terms:
            mode = "lexical_rescue"
        return ranked[:top_k], {"mode": mode, "eligible_candidates": len(memories) - rejected}

    def _lexical_model(self, memories, prompt_terms, blocked, sensitivity_policy):
        model = {"terms": set(prompt_terms), "weights": {}, "total_weight": 1.0}
        if not prompt_terms:
            return model
        frequencies = {term: 0 for term in prompt_terms}
        candidate_count = 0
        for memory in memories:
            if memory.sensitivity_level in blocked and sensitivity_policy == "strict":
                continue
            terms = self._memory_terms(serialize_memory(memory))
            matches = prompt_terms & terms
            if not matches:
                continue
            candidate_count += 1
            for term in matches:
                frequencies[term] += 1
        if not candidate_count:
            model["weights"] = {term: max(len(term), 1) for term in prompt_terms}
        else:
            model["weights"] = {
                term: (1.0 + math.log((candidate_count + 1) / (frequencies.get(term, 0) + 1))) * max(len(term), 1)
                for term in prompt_terms
            }
        model["total_weight"] = sum(model["weights"].values()) or 1.0
        supported = {term for term, count in frequencies.items() if count > 0}
        if supported:
            max_supported = max(model["weights"][term] for term in supported)
            model["specific_terms"] = {term for term in supported if model["weights"][term] >= max_supported * 0.9}
            unsupported = set(prompt_terms) - supported
            strongest_unsupported = max(unsupported, key=lambda term: model["weights"][term], default=None)
            strongest_supported = max(supported, key=lambda term: model["weights"][term], default=None)
            model["weak_only"] = (
                bool(strongest_unsupported and strongest_supported)
                and model["weights"][strongest_unsupported] > max_supported * 1.7
                and len(strongest_unsupported) >= len(strongest_supported) + 2
            )
        else:
            model["specific_terms"] = set()
            model["weak_only"] = False
        return model

    def _lexical_score(self, memory, model):
        prompt_terms = model["terms"]
        if not prompt_terms:
            return 0.0, set()
        memory_terms = self._memory_terms(memory)
        matches = prompt_terms & memory_terms
        if not matches:
            return 0.0, set()
        if model.get("weak_only"):
            return 0.0, matches
        specific_terms = model.get("specific_terms") or set()
        if specific_terms and not (matches & specific_terms):
            return 0.0, matches
        score = sum(model["weights"][term] for term in matches) / model["total_weight"]
        return score, matches

    def _memory_has_evidence(self, memory, prompt_terms):
        memory_terms = self._memory_terms(memory)
        return bool(prompt_terms & memory_terms)

    def _memory_terms(self, memory):
        return self._query_terms(
            " ".join(
                [
                    memory.get("title") or "",
                    memory.get("summary") or "",
                    memory.get("content") or "",
                    " ".join(memory.get("tags") or []),
                ]
            )
        )

    def _query_terms(self, text):
        return {self._singular_term(term) for term in self.memory_service._query_terms(text) if term}

    def _singular_term(self, term):
        if len(term) > 4 and term.endswith("ies"):
            return f"{term[:-3]}y"
        if len(term) > 3 and term.endswith("s"):
            return term[:-1]
        return term

    def _semantic_score(self, result):
        if not result:
            return 0.0
        return float(result.get("semantic_score") or result.get("vector_score") or 0.0)

    def _result_correlations(self, memory_id, payload):
        if not payload.get("include_correlations"):
            return []
        return serialize_correlations(
            memory_id,
            limit=int(payload.get("correlation_limit", 5)),
            min_strength=float(payload.get("min_correlation_strength", 0.35)),
        )


def confirm_memory(memory_id):
    memory = db.session.get(Memory, memory_id)
    if memory:
        memory.confirmed = True
        memory.pending_approval = False
        db.session.commit()
    return memory
