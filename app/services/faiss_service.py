import json
import logging
from datetime import datetime
from pathlib import Path
from time import perf_counter

import numpy as np
from flask import current_app

from app.extensions import db
from app.models import Memory, MemoryEmbedding, MemoryVector, Workspace

logger = logging.getLogger(__name__)


class FaissService:
    """Workspace FAISS indexes using normalized vectors and stable vector IDs."""

    INDEX_TYPE = "IndexIDMap2(IndexFlatIP)"
    _index_cache = {}
    _vector_map_cache = {}
    _cache_hits = 0
    _cache_misses = 0

    def __init__(self, index_dir):
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)

    def _paths(self, workspace_id):
        return (
            self.index_dir / f"workspace_{workspace_id}.faiss",
            self.index_dir / f"workspace_{workspace_id}.json",
        )

    def index_name(self, workspace_id):
        return f"workspace_{workspace_id}"

    def _load_faiss(self):
        import faiss

        return faiss

    def _normalize(self, vector):
        array = np.asarray(vector, dtype="float32").reshape(1, -1)
        norm = np.linalg.norm(array)
        if norm:
            array = array / norm
        return np.ascontiguousarray(array.astype("float32"))

    def _new_index(self, dim):
        faiss = self._load_faiss()
        return faiss.IndexIDMap2(faiss.IndexFlatIP(int(dim)))

    def _read_or_create_index(self, workspace_id, dim):
        index_path, _ = self._paths(workspace_id)
        if not index_path.exists():
            return self._new_index(dim)
        index = self._read_index_cached(workspace_id)
        if not hasattr(index, "id_map"):
            logger.warning("Legacy FAISS index without ID map for workspace %s; replacing with ID-mapped index", workspace_id)
            return self._new_index(dim)
        if index.d != dim:
            logger.warning(
                "FAISS dimension mismatch for workspace %s: index=%s query=%s; rebuilding required",
                workspace_id,
                index.d,
                dim,
            )
            return self._new_index(dim)
        return index

    def rebuild(self, workspace_id, embedding_service):
        workspace_id = int(workspace_id)
        memories = (
            Memory.query.filter_by(workspace_id=workspace_id, archived=False, deleted_at=None)
            .order_by(Memory.id.asc())
            .all()
        )
        vectors = []
        ids = []
        vector_rows = []
        dim = None
        index_name = self.index_name(workspace_id)
        embedding_model = embedding_service.model_name
        logger.info("Rebuilding FAISS index workspace=%s memories=%s model=%s", workspace_id, len(memories), embedding_model)
        for memory in memories:
            vector = self._normalize(embedding_service.embed(memory.content))
            dim = vector.shape[1]
            vector_id = int(memory.id)
            vectors.append(vector[0])
            ids.append(vector_id)
            embedding_hash = embedding_service.hash(vector[0])
            memory.embedding_hash = embedding_hash
            vector_rows.append(
                MemoryVector(
                    memory_id=memory.id,
                    workspace_id=memory.workspace_id,
                    agent_id=memory.agent_id,
                    vector_id=vector_id,
                    embedding_model=embedding_model,
                    vector_dim=dim,
                    embedding_hash=embedding_hash,
                    content_hash=memory.content_hash,
                    faiss_index_name=index_name,
                )
            )
            legacy = MemoryEmbedding.query.filter_by(memory_id=memory.id).first()
            if legacy:
                legacy.workspace_id = memory.workspace_id
                legacy.embedding_hash = embedding_hash
                legacy.vector_dim = dim
                legacy.faiss_position = vector_id
            else:
                db.session.add(
                    MemoryEmbedding(
                        memory_id=memory.id,
                        workspace_id=memory.workspace_id,
                        embedding_hash=embedding_hash,
                        vector_dim=dim,
                        faiss_position=vector_id,
                    )
                )
        dim = dim or 384
        index = self._new_index(dim)
        if vectors:
            index.add_with_ids(np.vstack(vectors).astype("float32"), np.asarray(ids, dtype="int64"))
        MemoryVector.query.filter_by(workspace_id=workspace_id).delete()
        self._vector_map_cache.pop(workspace_id, None)
        db.session.add_all(vector_rows)
        db.session.commit()
        index_path, meta_path = self._paths(workspace_id)
        self._load_faiss().write_index(index, str(index_path))
        self._store_index_cache(workspace_id, index)
        meta_path.write_text(
            json.dumps(
                {
                    "workspace_id": workspace_id,
                    "embedding_model": embedding_model,
                    "vector_dim": dim,
                    "index_type": self.INDEX_TYPE,
                    "total_vectors": len(ids),
                    "last_rebuild_at": datetime.utcnow().isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.info("Rebuilt FAISS index workspace=%s vectors=%s dim=%s", workspace_id, len(ids), dim)
        return {"workspace_id": workspace_id, "count": len(ids), "dim": dim, "index_type": self.INDEX_TYPE}

    def upsert_memory(self, memory, embedding_service, vector=None):
        workspace_id = int(memory.workspace_id)
        vector = self._normalize(vector if vector is not None else embedding_service.embed(memory.content))
        dim = vector.shape[1]
        index_path, meta_path = self._paths(workspace_id)
        index = self._read_or_create_index(workspace_id, dim)
        vector_id = int(memory.id)
        ids = np.asarray([vector_id], dtype="int64")
        try:
            index.remove_ids(ids)
        except Exception:
            logger.debug("FAISS remove before upsert skipped workspace=%s vector_id=%s", workspace_id, vector_id)
        index.add_with_ids(vector, ids)
        self._load_faiss().write_index(index, str(index_path))
        self._store_index_cache(workspace_id, index)
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except ValueError:
                meta = {}
        meta.update(
            {
                "workspace_id": workspace_id,
                "embedding_model": embedding_service.model_name,
                "vector_dim": dim,
                "index_type": self.INDEX_TYPE,
                "total_vectors": int(index.ntotal),
                "last_rebuild_at": meta.get("last_rebuild_at"),
                "last_upsert_at": datetime.utcnow().isoformat(),
            }
        )
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        embedding_hash = embedding_service.hash(vector[0])
        memory.embedding_hash = embedding_hash
        row = MemoryVector.query.filter_by(memory_id=memory.id).first()
        if not row:
            row = MemoryVector(memory_id=memory.id)
            db.session.add(row)
        row.workspace_id = workspace_id
        row.agent_id = memory.agent_id
        row.vector_id = vector_id
        row.embedding_model = embedding_service.model_name
        row.vector_dim = dim
        row.embedding_hash = embedding_hash
        row.content_hash = memory.content_hash
        row.faiss_index_name = self.index_name(workspace_id)
        legacy = MemoryEmbedding.query.filter_by(memory_id=memory.id).first()
        if not legacy:
            legacy = MemoryEmbedding(memory_id=memory.id, workspace_id=workspace_id, embedding_hash=embedding_hash, vector_dim=dim)
            db.session.add(legacy)
        legacy.workspace_id = workspace_id
        legacy.embedding_hash = embedding_hash
        legacy.vector_dim = dim
        legacy.faiss_position = vector_id
        db.session.commit()
        self._cache_vector_rows(workspace_id, [row])
        logger.debug("Upserted FAISS vector workspace=%s memory_id=%s vector_id=%s dim=%s", workspace_id, memory.id, vector_id, dim)
        return row

    def search(self, workspace_id, query_vector, top_k, timing=None):
        workspace_id = int(workspace_id)
        index_path, _ = self._paths(workspace_id)
        if not index_path.exists():
            logger.warning("FAISS index missing workspace=%s path=%s", workspace_id, index_path)
            return []
        query = self._normalize(query_vector)
        try:
            load_started = perf_counter()
            index = self._read_index_cached(workspace_id)
            if timing is not None:
                timing["faiss_load_ms"] = self._elapsed_ms(load_started)
            if index.d != query.shape[1]:
                logger.error("FAISS query dimension mismatch workspace=%s index=%s query=%s", workspace_id, index.d, query.shape[1])
                return []
            search_started = perf_counter()
            scores, vector_ids = index.search(query, int(top_k))
            if timing is not None:
                timing["faiss_search_ms"] = self._elapsed_ms(search_started)
        except Exception as exc:
            logger.error("FAISS index unavailable for workspace %s: %s", workspace_id, exc)
            return []
        ids = [int(vector_id) for vector_id in vector_ids[0] if int(vector_id) >= 0]
        map_started = perf_counter()
        rows = self._vector_rows_for_ids(workspace_id, ids)
        if timing is not None:
            timing["vector_map_ms"] = self._elapsed_ms(map_started)
        results = []
        for raw_score, raw_vector_id in zip(scores[0], vector_ids[0]):
            vector_id = int(raw_vector_id)
            if vector_id < 0:
                continue
            row = rows.get(vector_id)
            if not row:
                logger.warning("FAISS returned unmapped vector workspace=%s vector_id=%s", workspace_id, vector_id)
                continue
            semantic_score = max(0.0, min(1.0, float(raw_score)))
            results.append(
                {
                    "memory_id": row.memory_id,
                    "vector_id": vector_id,
                    "semantic_score": semantic_score,
                    "raw_score": float(raw_score),
                    "faiss_index_name": row.faiss_index_name,
                    "embedding_model": row.embedding_model,
                    "vector_dim": row.vector_dim,
                    "embedding_hash": row.embedding_hash,
                    "source": "faiss",
                }
            )
        logger.debug(
            "FAISS search workspace=%s top_k=%s returned=%s mapped=%s",
            workspace_id,
            top_k,
            len(ids),
            len(results),
        )
        return results

    def _read_index_cached(self, workspace_id):
        index_path, _ = self._paths(workspace_id)
        stat = index_path.stat()
        cache_key = (str(index_path), int(workspace_id))
        cached = self._index_cache.get(cache_key)
        if cached and cached["mtime"] == stat.st_mtime_ns and cached["size"] == stat.st_size:
            self.__class__._cache_hits += 1
            return cached["index"]
        self.__class__._cache_misses += 1
        index = self._load_faiss().read_index(str(index_path))
        self._index_cache[cache_key] = {"mtime": stat.st_mtime_ns, "size": stat.st_size, "index": index}
        return index

    def _store_index_cache(self, workspace_id, index):
        index_path, _ = self._paths(workspace_id)
        if not index_path.exists():
            return
        stat = index_path.stat()
        self._index_cache[(str(index_path), int(workspace_id))] = {
            "mtime": stat.st_mtime_ns,
            "size": stat.st_size,
            "index": index,
        }

    def _vector_rows_for_ids(self, workspace_id, vector_ids):
        if not vector_ids:
            return {}
        cache_key = int(workspace_id)
        cached = self._vector_map_cache.get(cache_key)
        missing = set(vector_ids)
        rows = {}
        if cached:
            rows.update({vector_id: cached[vector_id] for vector_id in vector_ids if vector_id in cached})
            missing -= set(rows.keys())
        if missing:
            db_rows = MemoryVector.query.filter(
                MemoryVector.workspace_id == workspace_id,
                MemoryVector.vector_id.in_(missing),
            ).all()
            self._cache_vector_rows(workspace_id, db_rows)
            rows.update({row.vector_id: self._row_dto(row) for row in db_rows})
        return rows

    def _cache_vector_rows(self, workspace_id, rows):
        cache = self._vector_map_cache.setdefault(int(workspace_id), {})
        for row in rows:
            cache[row.vector_id] = self._row_dto(row)

    def _row_dto(self, row):
        class VectorRowDTO:
            pass

        dto = VectorRowDTO()
        dto.memory_id = row.memory_id
        dto.vector_id = row.vector_id
        dto.faiss_index_name = row.faiss_index_name
        dto.embedding_model = row.embedding_model
        dto.vector_dim = row.vector_dim
        dto.embedding_hash = row.embedding_hash
        return dto

    def _elapsed_ms(self, started):
        return round((perf_counter() - started) * 1000, 2)

    def _index_vector_ids(self, workspace_id):
        faiss = self._load_faiss()
        index_path, _ = self._paths(workspace_id)
        if not index_path.exists():
            return set(), None
        index = self._read_index_cached(workspace_id)
        try:
            ids = set(int(value) for value in faiss.vector_to_array(index.id_map))
        except Exception:
            ids = set()
        return ids, index

    def status(self, workspace_id):
        index_path, meta_path = self._paths(workspace_id)
        if not index_path.exists():
            return {"status": "missing", "count": 0, "index_type": self.INDEX_TYPE}
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            ids, index = self._index_vector_ids(workspace_id)
            return {
                "status": "ready",
                "count": int(index.ntotal) if index else 0,
                "path": str(index_path),
                "index_type": self.INDEX_TYPE,
                "vector_dim": int(index.d) if index else meta.get("vector_dim"),
                "last_rebuild_at": meta.get("last_rebuild_at"),
                "last_upsert_at": meta.get("last_upsert_at"),
                "mapped_vector_ids": len(ids),
            }
        except Exception as exc:
            logger.error("FAISS status failed workspace=%s: %s", workspace_id, exc)
            return {"status": "corrupt", "count": 0, "index_type": self.INDEX_TYPE}

    def health(self):
        indexes = []
        total_vectors = 0
        missing_faiss_vectors = 0
        orphan_database_vectors = 0
        last_rebuild = None
        for workspace in Workspace.query.order_by(Workspace.id.asc()).all():
            status = self.status(workspace.id)
            db_vectors = MemoryVector.query.filter_by(workspace_id=workspace.id).all()
            db_ids = {row.vector_id for row in db_vectors}
            try:
                faiss_ids, index = self._index_vector_ids(workspace.id)
            except Exception:
                faiss_ids, index = set(), None
            total_vectors += int(status.get("count") or 0)
            missing_faiss_vectors += len(db_ids - faiss_ids)
            active_memory_ids = {
                mid
                for (mid,) in Memory.query.with_entities(Memory.id)
                .filter_by(workspace_id=workspace.id, archived=False, deleted_at=None)
                .all()
            }
            orphan_database_vectors += len({row.memory_id for row in db_vectors} - active_memory_ids)
            indexes.append(
                {
                    "workspace_id": workspace.id,
                    "workspace": workspace.name,
                    "status": status.get("status"),
                    "vectors": status.get("count", 0),
                    "vector_dim": status.get("vector_dim"),
                    "path": status.get("path"),
                }
            )
            last_rebuild = status.get("last_rebuild_at") or last_rebuild
        memories_without_vectors = (
            Memory.query.filter_by(archived=False, deleted_at=None)
            .outerjoin(MemoryVector, MemoryVector.memory_id == Memory.id)
            .filter(MemoryVector.id.is_(None))
            .count()
        )
        model = current_app.config["EMBEDDING_MODEL"]
        return {
            "loaded_indexes": indexes,
            "embedding_model": model,
            "embedding_dimension": self._configured_dimension(),
            "faiss_index_type": self.INDEX_TYPE,
            "total_vectors": total_vectors,
            "orphan_database_vectors": orphan_database_vectors,
            "missing_faiss_vectors": missing_faiss_vectors,
            "memories_without_vectors": memories_without_vectors,
            "last_index_rebuild_time": last_rebuild,
        }

    def warmup(self, embedding_service=None):
        from app.services.embedding_service import EmbeddingService
        from app.services.settings_service import SettingsService

        embedding_service = embedding_service or EmbeddingService(
            SettingsService.get("embedding_model", current_app.config["EMBEDDING_MODEL"])
        )
        model_started = perf_counter()
        probe = embedding_service.embed("warmup")
        model_ms = self._elapsed_ms(model_started)
        loaded = []
        for workspace in Workspace.query.order_by(Workspace.id.asc()).all():
            index_path, _ = self._paths(workspace.id)
            if not index_path.exists():
                if current_app.config.get("VECTOR_AUTO_REPAIR_ON_WARMUP", True):
                    self.rebuild(workspace.id, embedding_service)
                else:
                    continue
            index_started = perf_counter()
            index = self._read_index_cached(workspace.id)
            expected_ids = {
                row.vector_id
                for row in MemoryVector.query.filter_by(workspace_id=workspace.id).all()
            }
            try:
                actual_ids = set(int(value) for value in self._load_faiss().vector_to_array(index.id_map))
            except Exception:
                actual_ids = set()
            if current_app.config.get("VECTOR_AUTO_REPAIR_ON_WARMUP", True) and expected_ids != actual_ids:
                logger.warning(
                    "Repairing stale FAISS index workspace=%s expected_vectors=%s actual_vectors=%s missing=%s extra=%s",
                    workspace.id,
                    len(expected_ids),
                    len(actual_ids),
                    len(expected_ids - actual_ids),
                    len(actual_ids - expected_ids),
                )
                self.rebuild(workspace.id, embedding_service)
                index = self._read_index_cached(workspace.id)
            self.search(workspace.id, probe, 1)
            loaded.append({"workspace_id": workspace.id, "vectors": int(index.ntotal), "load_ms": self._elapsed_ms(index_started)})
        return {"embedding_ms": model_ms, "loaded_indexes": loaded, "cache": self.cache_stats()}

    @classmethod
    def cache_stats(cls):
        total = cls._cache_hits + cls._cache_misses
        return {
            "index_cache_entries": len(cls._index_cache),
            "vector_map_cache_entries": sum(len(value) for value in cls._vector_map_cache.values()),
            "cache_hits": cls._cache_hits,
            "cache_misses": cls._cache_misses,
            "cache_hit_ratio": round(cls._cache_hits / total, 4) if total else 0,
        }

    def _configured_dimension(self):
        row = MemoryVector.query.order_by(MemoryVector.updated_at.desc()).first()
        return row.vector_dim if row else None
