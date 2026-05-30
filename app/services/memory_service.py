import re
from datetime import datetime
from time import perf_counter

from flask import current_app
from sqlalchemy import or_

from app.extensions import db
from app.models import Memory, MemoryAsset, MemoryCorrelation, MemoryEmbedding, MemoryVector
from app.repositories.memory_repository import MemoryRepository
from app.services.audit_service import AuditService
from app.services.embedding_service import EmbeddingService
from app.services.faiss_service import FaissService
from app.services.performance_service import PerformanceService
from app.services.reranker_service import RerankerService
from app.services.settings_service import SettingsService
from app.utils.hash import sha256_text


class MemoryService:
    def __init__(self):
        self.repo = MemoryRepository()
        self.embedding_service = EmbeddingService(SettingsService.get("embedding_model", current_app.config["EMBEDDING_MODEL"]))
        self.faiss = FaissService(current_app.config["FAISS_INDEX_DIR"])

    def add_memory(self, payload, actor_type="agent", actor_id=None):
        required = ["agent_id", "workspace_id", "content", "memory_type"]
        missing = [field for field in required if not payload.get(field)]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")

        content_hash = sha256_text(payload["content"].strip())
        existing = Memory.query.filter_by(workspace_id=payload["workspace_id"], content_hash=content_hash).first()
        if existing and existing.deleted_at is None:
            existing.trust_score = min(1.0, existing.trust_score + 0.05)
            existing.updated_at = datetime.utcnow()
            AuditService.log("memory.duplicate_seen", actor_type, actor_id, existing.workspace_id, "memory", existing.id)
            db.session.commit()
            if not MemoryVector.query.filter_by(memory_id=existing.id).first():
                self.faiss.upsert_memory(existing, self.embedding_service)
            return existing, True

        vector = self.embedding_service.embed(payload["content"])
        embedding_hash = self.embedding_service.hash(vector)
        memory = self.repo.create(
            agent_id=payload["agent_id"],
            workspace_id=payload["workspace_id"],
            session_id=payload.get("session_id"),
            source_session_id=payload.get("source_session_id"),
            title=payload.get("title") or payload["content"][:100],
            content=payload["content"],
            summary=payload.get("summary"),
            memory_type=payload["memory_type"],
            tags=payload.get("tags") or [],
            importance_score=float(payload.get("importance_score", 0.5)),
            trust_score=float(payload.get("trust_score", 0.5)),
            sensitivity_level=payload.get("sensitivity_level", "normal"),
            visibility=payload.get("visibility", "workspace"),
            embedding_hash=embedding_hash,
            content_hash=content_hash,
            source=payload.get("source", "api"),
            created_by=payload.get("created_by", actor_type),
            expires_at=payload.get("expires_at"),
            confirmed=bool(payload.get("confirmed", False)),
            pending_approval=not bool(payload.get("confirmed", False)),
            storage_reason=payload.get("storage_reason", "Stored by memory API or consolidation policy."),
        )
        AuditService.log("memory.created", actor_type, actor_id, memory.workspace_id, "memory", memory.id)
        db.session.commit()
        try:
            self.faiss.upsert_memory(memory, self.embedding_service, vector=vector)
        except Exception:
            current_app.logger.exception("Could not upsert FAISS vector after memory create")
        try:
            from app.services.correlation_service import CorrelationService

            CorrelationService().correlate_memory(memory)
        except Exception:
            current_app.logger.exception("Could not correlate memory after create")
        return memory, False

    def search(self, payload, semantic=True):
        started = perf_counter()
        timing = {
            "embedding_ms": 0,
            "faiss_load_ms": 0,
            "faiss_search_ms": 0,
            "vector_map_ms": 0,
            "db_lookup_ms": 0,
            "correlation_ms": 0,
            "rerank_ms": 0,
            "reranker_enabled": False,
            "reranker_provider": "none",
            "reranker_model": None,
            "reranker_used": False,
            "reranker_reason": None,
            "reranker_ms": 0,
            "serialization_ms": 0,
            "total_ms": 0,
        }
        mode = (payload.get("mode") or ("agent" if payload.get("compact") else "ui")).lower()
        workspace_id = int(payload["workspace_id"])
        base_query = self.repo.query_scope(workspace_id, include_archived=bool(payload.get("include_archived")))
        base_query = self._apply_filters(base_query, payload)
        keyword = payload.get("query") or payload.get("prompt") or ""
        semantic_hits = {}
        vector_hits = {}
        query_vector = None
        if semantic and keyword:
            stage = perf_counter()
            query_vector = self.embedding_service.embed(keyword)
            timing["embedding_ms"] = round((perf_counter() - stage) * 1000, 2)
            faiss_results = self.faiss.search(workspace_id, query_vector, int(payload.get("top_k", 10)) * 5, timing=timing)
            vector_hits = {item["memory_id"]: item for item in faiss_results}
            semantic_hits = {memory_id: item["semantic_score"] for memory_id, item in vector_hits.items()}
            current_app.logger.debug(
                "Memory semantic search workspace=%s query=%r faiss_hits=%s",
                workspace_id,
                keyword[:120],
                len(semantic_hits),
            )
        terms = self._query_terms(keyword)
        clauses = [or_(Memory.content.ilike(f"%{term}%"), Memory.title.ilike(f"%{term}%")) for term in terms]
        candidate_limit = max(int(payload.get("top_k", 20)) * 10, 100)
        candidate_query = base_query
        if semantic_hits:
            candidate_query = base_query.filter(Memory.id.in_(semantic_hits.keys()))
        elif terms:
            candidate_query = base_query.filter(or_(*clauses))
        stage = perf_counter()
        memories = candidate_query.order_by(Memory.updated_at.desc()).limit(candidate_limit).all()
        if semantic_hits and clauses:
            memory_by_id = {memory.id: memory for memory in memories}
            keyword_memories = base_query.filter(or_(*clauses)).order_by(Memory.updated_at.desc()).limit(candidate_limit).all()
            for memory in keyword_memories:
                memory_by_id.setdefault(memory.id, memory)
            memories = list(memory_by_id.values())
        timing["db_lookup_ms"] = round((perf_counter() - stage) * 1000, 2)
        stage = perf_counter()
        ranked = []
        now = datetime.utcnow()
        for memory in memories:
            recency = 1 / max((now - memory.created_at).days + 1, 1)
            keyword_score = self._keyword_score(keyword, memory)
            semantic_score = semantic_hits.get(memory.id, 0.0)
            if semantic_hits and semantic_score <= 0 and keyword_score <= 0:
                continue
            if semantic_hits and semantic_score < float(payload.get("min_semantic_score", 0.25)) and keyword_score < float(payload.get("min_keyword_score", 0.5)):
                continue
            score = (
                max(semantic_score, 0.0) * 0.60
                + keyword_score * 0.15
                + memory.trust_score * 0.10
                + memory.importance_score * 0.10
                + recency * 0.05
            )
            if score >= float(payload.get("min_relevance_score", 0.18)):
                ranked.append((score, memory, semantic_score, vector_hits.get(memory.id)))
        ranked.sort(key=lambda item: item[0], reverse=True)
        ranked = ranked[: int(payload.get("top_k", 20))]
        timing["rerank_ms"] = round((perf_counter() - stage) * 1000, 2)
        if semantic_hits and not ranked and terms:
            fallback_started = perf_counter()
            fallback_memories = (
                base_query.filter(or_(*clauses))
                .order_by(Memory.updated_at.desc())
                .limit(candidate_limit)
                .all()
            )
            timing["keyword_fallback_ms"] = round((perf_counter() - fallback_started) * 1000, 2)
            stage = perf_counter()
            ranked = []
            for memory in fallback_memories:
                recency = 1 / max((now - memory.created_at).days + 1, 1)
                keyword_score = self._keyword_score(keyword, memory)
                if keyword_score <= 0:
                    continue
                score = keyword_score * 0.70 + memory.trust_score * 0.10 + memory.importance_score * 0.10 + recency * 0.10
                if score >= float(payload.get("min_relevance_score", 0.18)):
                    ranked.append((score, memory, 0.0, None))
            ranked.sort(key=lambda item: item[0], reverse=True)
            ranked = ranked[: int(payload.get("top_k", 20))]
            timing["rerank_ms"] = round(timing["rerank_ms"] + ((perf_counter() - stage) * 1000), 2)
        ranked_entries = [
            {
                "score": float(score),
                "final_score": float(score),
                "memory": memory,
                "semantic_score": float(semantic_score),
                "vector_hit": vector_hit,
                "reranker_score": None,
                "reranker_reason": None,
            }
            for score, memory, semantic_score, vector_hit in ranked
        ]
        ranked_entries, reranker_meta = RerankerService().maybe_rerank(keyword, ranked_entries, payload, mode)
        timing["reranker_enabled"] = reranker_meta["enabled"]
        timing["reranker_provider"] = reranker_meta["provider"]
        timing["reranker_model"] = reranker_meta["model"]
        timing["reranker_used"] = reranker_meta["used"]
        timing["reranker_reason"] = reranker_meta["reason"]
        timing["reranker_ms"] = reranker_meta["ms"]
        if payload.get("record_access", True):
            for item in ranked_entries:
                memory = item["memory"]
                self.repo.mark_accessed(memory, payload.get("agent_id"), "search")
            db.session.commit()
        include_vector_details = bool(payload.get("include_vector_details") or payload.get("include_vectors") or mode == "debug")
        include_correlations = bool(payload.get("include_correlations") or payload.get("with_correlations") or mode == "debug")
        compact = bool(payload.get("compact") or mode == "agent")
        vectors_by_memory = {}
        if include_vector_details and ranked_entries:
            vectors_by_memory = {
                row.memory_id: row
                for row in MemoryVector.query.filter(MemoryVector.memory_id.in_([item["memory"].id for item in ranked_entries])).all()
            }
        stage = perf_counter()
        results = []
        for entry in ranked_entries:
            score = entry["final_score"]
            memory = entry["memory"]
            semantic_score = entry["semantic_score"]
            vector_hit = entry["vector_hit"]
            if compact:
                item = serialize_search_result_compact(memory, score, semantic_score, entry)
                item["retrieved_by"] = "reranked" if reranker_meta["used"] else ("semantic_vector" if vector_hit else "keyword_fallback")
                item["reranker_provider"] = reranker_meta["provider"]
                item["reranker_model"] = reranker_meta["model"]
                if include_vector_details:
                    item["vector_id"] = (vectors_by_memory.get(memory.id).vector_id if vectors_by_memory.get(memory.id) else None) or (vector_hit or {}).get("vector_id")
                results.append(item)
                continue
            item = {
                "memory": serialize_memory(memory, include_assets=mode != "agent" or bool(payload.get("include_assets"))),
                "relevance_score": round(score, 4),
                "final_score": round(score, 4),
                "vector_score": round(semantic_score, 4),
                "semantic_score": round(semantic_score, 4),
                "reranker_score": round(entry["reranker_score"], 4) if entry["reranker_score"] is not None else None,
                "reranked": bool(reranker_meta["used"]),
                "reranker_provider": reranker_meta["provider"],
                "reranker_model": reranker_meta["model"],
                "retrieved_by": "reranked" if reranker_meta["used"] else ("semantic_vector" if vector_hit else "keyword_fallback"),
                "explanation": {
                    "semantic_similarity": round(semantic_score, 4),
                    "keyword_match": round(self._keyword_score(keyword, memory), 4),
                    "importance": memory.importance_score,
                    "trust": memory.trust_score,
                    "access_count": memory.access_count,
                },
            }
            if mode == "debug" and entry.get("reranker_reason"):
                item["reranker_reason"] = entry["reranker_reason"]
            if include_vector_details:
                item["vector"] = self._vector_metadata(memory, semantic_score, vector_hit, vector=vectors_by_memory.get(memory.id))
            if include_correlations:
                correlation_stage = perf_counter()
                item["correlations"] = serialize_correlations(
                    memory.id,
                    limit=int(payload.get("correlation_limit", 5)),
                    min_strength=float(payload.get("min_correlation_strength", 0.35)),
                )
                timing["correlation_ms"] += round((perf_counter() - correlation_stage) * 1000, 2)
            item["agent_evidence"] = self._agent_evidence(item)
            results.append(item)
        timing["serialization_ms"] = round((perf_counter() - stage) * 1000, 2)
        timing["correlation_ms"] = round(timing["correlation_ms"], 2)
        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        timing["total_ms"] = elapsed_ms
        timing["elapsed_ms"] = elapsed_ms
        timing["result_count"] = len(results)
        timing["semantic"] = bool(semantic)
        timing["mode"] = mode
        PerformanceService.record_search(timing)
        if payload.get("include_timing"):
            return {
                "results": results,
                "timing": timing,
            }
        return results

    def _vector_metadata(self, memory, semantic_score, vector_hit=None, vector=None):
        vector = vector or MemoryVector.query.filter_by(memory_id=memory.id).first()
        embedding = MemoryEmbedding.query.filter_by(memory_id=memory.id).first()
        return {
            "score": round(float(semantic_score), 4),
            "source": (vector_hit or {}).get("source", "faiss" if vector_hit else "metadata"),
            "retrieved_by": "semantic_vector" if vector_hit else "metadata_only",
            "vector_id": vector.vector_id if vector else (vector_hit or {}).get("vector_id"),
            "embedding_model": vector.embedding_model if vector else (vector_hit or {}).get("embedding_model"),
            "embedding_hash": memory.embedding_hash,
            "stored_embedding_hash": (vector.embedding_hash if vector else None) or (embedding.embedding_hash if embedding else None),
            "vector_dim": (vector.vector_dim if vector else None) or (embedding.vector_dim if embedding else None),
            "faiss_position": embedding.faiss_position if embedding else None,
            "faiss_index_name": vector.faiss_index_name if vector else (vector_hit or {}).get("faiss_index_name"),
            "raw_score": round(float((vector_hit or {}).get("raw_score", semantic_score)), 4),
        }

    def _agent_evidence(self, item):
        memory = item["memory"]
        return {
            "memory_id": memory["id"],
            "title": memory["title"],
            "answer_hint": self._answer_hint(memory, item),
            "scores": {
                "overall": item["relevance_score"],
                "semantic": item["semantic_score"],
                "keyword": item["explanation"]["keyword_match"],
                "trust": memory["trust_score"],
                "importance": memory["importance_score"],
            },
            "use_when": f"Use this when answering about {', '.join(memory.get('tags') or [memory['memory_type']])}.",
            "assets": memory.get("assets", []),
        }

    def _answer_hint(self, memory, item):
        content = memory.get("content") or ""
        title = memory.get("title") or ""
        terms = set()
        for text in [title, " ".join(memory.get("tags") or [])]:
            terms |= {word.lower().strip(".,:;!?()[]{}") for word in text.split() if len(word) > 3}
        # Prefer lines with contact/address cues because agents usually ask concrete questions.
        priority_terms = ["address", "email", "phone", "fax", "contact", "headquartered", "location"]
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        matched = [line for line in lines if any(term in line.lower() for term in priority_terms)]
        if matched:
            return "\n".join(matched[:6])
        if memory.get("summary") and len(content) < 300:
            return memory["summary"]
        return content[:1200]

    def _apply_filters(self, query, payload):
        if payload.get("agent_id"):
            query = query.filter(Memory.agent_id == int(payload["agent_id"]))
        if payload.get("memory_types"):
            query = query.filter(Memory.memory_type.in_(payload["memory_types"]))
        if payload.get("sensitivity_level"):
            query = query.filter(Memory.sensitivity_level == payload["sensitivity_level"])
        if payload.get("min_trust"):
            query = query.filter(Memory.trust_score >= float(payload["min_trust"]))
        if payload.get("tags"):
            for tag in payload["tags"]:
                query = query.filter(Memory.tags.contains([tag]))
        return query

    def _keyword_score(self, keyword, memory):
        terms = self._query_terms(keyword)
        haystack = f"{memory.title} {memory.content} {' '.join(memory.tags or [])}".lower()
        haystack_terms = set(self._query_terms(haystack))
        if not terms:
            return 0.0
        matches = sum(1 for term in terms if term in haystack_terms)
        return matches / len(terms)

    def _query_terms(self, text):
        stop_words = {
            "a",
            "an",
            "and",
            "are",
            "can",
            "did",
            "does",
            "for",
            "from",
            "have",
            "has",
            "how",
            "is",
            "me",
            "of",
            "or",
            "the",
            "to",
            "was",
            "what",
            "when",
            "where",
            "which",
            "who",
            "why",
            "with",
        }
        terms = []
        for raw in re.findall(r"[a-zA-Z0-9']+", (text or "").lower()):
            term = raw.removesuffix("'s").strip("'")
            if len(term) > 2 and term not in stop_words:
                terms.append(term)
        return terms

    def archive(self, memory, actor_id=None):
        memory.archived = True
        AuditService.log("memory.archived", "agent", actor_id, memory.workspace_id, "memory", memory.id)
        db.session.commit()
        self._rebuild_workspace_index(memory.workspace_id)

    def delete(self, memory, actor_id=None, forget=False):
        memory.deleted_at = datetime.utcnow()
        memory.archived = True
        action = "memory.forgotten" if forget else "memory.deleted"
        AuditService.log(action, "agent", actor_id, memory.workspace_id, "memory", memory.id)
        db.session.commit()
        self._rebuild_workspace_index(memory.workspace_id)

    def _rebuild_workspace_index(self, workspace_id):
        try:
            self.faiss.rebuild(workspace_id, self.embedding_service)
        except Exception:
            current_app.logger.exception("Could not rebuild FAISS index for workspace %s", workspace_id)


def serialize_search_result_compact(memory, score, semantic_score, entry=None):
    entry = entry or {}
    return {
        "memory_id": memory.id,
        "title": memory.title,
        "content": memory.content,
        "memory_type": memory.memory_type,
        "tags": memory.tags or [],
        "semantic_score": round(float(semantic_score), 4),
        "vector_score": round(float(semantic_score), 4),
        "relevance_score": round(float(score), 4),
        "final_score": round(float(score), 4),
        "reranker_score": round(entry["reranker_score"], 4) if entry.get("reranker_score") is not None else None,
        "reranked": entry.get("reranker_score") is not None,
        "trust_score": memory.trust_score,
        "importance_score": memory.importance_score,
    }


def serialize_memory(memory, include_assets=True):
    assets = MemoryAsset.query.filter_by(memory_id=memory.id).all() if include_assets else []
    return {
        "id": memory.id,
        "uuid": memory.uuid,
        "agent_id": memory.agent_id,
        "workspace_id": memory.workspace_id,
        "session_id": memory.session_id,
        "source_session_id": memory.source_session_id,
        "title": memory.title,
        "content": memory.content,
        "summary": memory.summary,
        "memory_type": memory.memory_type,
        "tags": memory.tags,
        "importance_score": memory.importance_score,
        "trust_score": memory.trust_score,
        "sensitivity_level": memory.sensitivity_level,
        "visibility": memory.visibility,
        "source": memory.source,
        "created_by": memory.created_by,
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
        "last_accessed_at": memory.last_accessed_at.isoformat() if memory.last_accessed_at else None,
        "access_count": memory.access_count,
        "expires_at": memory.expires_at.isoformat() if memory.expires_at else None,
        "archived": memory.archived,
        "deleted_at": memory.deleted_at.isoformat() if memory.deleted_at else None,
        "confirmed": memory.confirmed,
        "pending_approval": memory.pending_approval,
        "storage_reason": memory.storage_reason,
        "assets": [serialize_asset(asset) for asset in assets],
    }


def serialize_asset(asset):
    return {
        "id": asset.uuid,
        "asset_type": asset.asset_type,
        "original_filename": asset.original_filename,
        "content_type": asset.content_type,
        "vector_hash": asset.vector_hash,
        "vector_dim": asset.vector_dim,
        "metadata": asset.asset_metadata,
        "url": f"/memory-assets/{asset.public_token}",
    }


def serialize_correlations(memory_id, limit=10, min_strength=0.35):
    correlations = (
        MemoryCorrelation.query.filter(
            (MemoryCorrelation.source_memory_id == memory_id) | (MemoryCorrelation.target_memory_id == memory_id)
        )
        .order_by(MemoryCorrelation.strength.desc())
        .all()
    )
    items = []
    for correlation in correlations:
        if correlation.strength < min_strength:
            continue
        related_id = correlation.target_memory_id if correlation.source_memory_id == memory_id else correlation.source_memory_id
        related = db.session.get(Memory, related_id)
        if not related or related.deleted_at:
            continue
        items.append(
            {
                "id": correlation.id,
                "memory_id": memory_id,
                "related_memory": serialize_memory(related),
                "correlation_type": correlation.correlation_type,
                "strength": round(correlation.strength, 4),
                "explanation": correlation.explanation,
                "created_at": correlation.created_at.isoformat() if correlation.created_at else None,
            }
        )
        if len(items) >= limit:
            break
    return items
