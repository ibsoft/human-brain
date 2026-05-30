import math
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from time import perf_counter

from flask import current_app

from app.models import AppSetting
from app.services.ollama_reranker_service import OllamaRerankerService
from app.services.settings_service import default_value


class RerankerService:
    _cross_encoder = None
    _cross_encoder_key = None
    _cross_encoder_future = None
    _cross_encoder_future_key = None
    _cross_encoder_loader = ThreadPoolExecutor(max_workers=1)
    _cross_encoder_lock = threading.Lock()

    def settings(self):
        keys = [
            "reranker_enabled",
            "reranker_provider",
            "reranker_default_mode",
            "reranker_cross_encoder_model",
            "reranker_ollama_base_url",
            "reranker_ollama_model",
            "reranker_top_n",
            "reranker_return_k",
            "reranker_timeout_ms",
            "reranker_weight",
            "faiss_weight",
            "trust_weight",
            "importance_weight",
            "reranker_conditional_threshold",
            "reranker_max_text_chars",
            "reranker_device",
        ]
        stored = {row.key: row.value for row in AppSetting.query.filter(AppSetting.key.in_(keys)).all()}
        value = lambda key: stored.get(key, default_value(key))
        return {
            "reranker_enabled": bool(value("reranker_enabled")),
            "reranker_provider": value("reranker_provider") or "none",
            "reranker_default_mode": value("reranker_default_mode") or "conditional",
            "reranker_cross_encoder_model": value("reranker_cross_encoder_model") or "BAAI/bge-reranker-base",
            "reranker_ollama_base_url": value("reranker_ollama_base_url") or "http://localhost:11434",
            "reranker_ollama_model": value("reranker_ollama_model") or "qwen2.5:7b",
            "reranker_top_n": max(1, int(value("reranker_top_n"))),
            "reranker_return_k": max(1, int(value("reranker_return_k"))),
            "reranker_timeout_ms": max(1, int(value("reranker_timeout_ms"))),
            "reranker_weight": max(0.0, float(value("reranker_weight"))),
            "faiss_weight": max(0.0, float(value("faiss_weight"))),
            "trust_weight": max(0.0, float(value("trust_weight"))),
            "importance_weight": max(0.0, float(value("importance_weight"))),
            "reranker_conditional_threshold": max(0.0, float(value("reranker_conditional_threshold"))),
            "reranker_max_text_chars": max(100, int(value("reranker_max_text_chars"))),
            "reranker_device": value("reranker_device") or "cpu",
        }

    def maybe_rerank(self, query, ranked, payload, mode):
        settings = self.settings()
        metadata = {
            "enabled": settings["reranker_enabled"],
            "provider": settings["reranker_provider"],
            "model": self._model_name(settings),
            "used": False,
            "ms": 0,
            "reason": "disabled",
        }
        if not self._should_rerank(settings, ranked, payload, mode):
            metadata["reason"] = self._skip_reason(settings, ranked)
            return ranked, metadata

        provider = settings["reranker_provider"]
        candidates = ranked[: settings["reranker_top_n"]]
        formatted = [self._candidate_payload(item["memory"], settings["reranker_max_text_chars"]) for item in candidates]
        started = perf_counter()
        try:
            if provider == "cross_encoder":
                if not self._cross_encoder_ready(settings):
                    metadata["reason"] = "cross_encoder_loading"
                    metadata["ms"] = round((perf_counter() - started) * 1000, 2)
                    return ranked, metadata
                scores, reasons = self._run_with_timeout(lambda: self._cross_encoder_scores(query, candidates, settings), settings)
            elif provider == "ollama":
                scores, reasons = self._run_with_timeout(lambda: OllamaRerankerService().rerank(query, formatted, settings), settings)
            else:
                metadata["reason"] = "provider_none"
                return ranked, metadata
        except Exception as exc:
            if current_app.debug:
                current_app.logger.debug("Reranker failed open: %s", exc, exc_info=True)
            metadata["ms"] = round((perf_counter() - started) * 1000, 2)
            metadata["reason"] = "failed_open"
            return ranked, metadata

        metadata["used"] = True
        metadata["ms"] = round((perf_counter() - started) * 1000, 2)
        metadata["reason"] = "reranked"
        for item in candidates:
            memory_id = item["memory"].id
            item["reranker_score"] = scores.get(memory_id, 0.0)
            item["reranker_reason"] = reasons.get(memory_id)
            item["final_score"] = self._final_score(item, settings)
        for item in ranked[settings["reranker_top_n"] :]:
            item["final_score"] = item["score"]
        reranked = sorted(candidates, key=lambda item: item["final_score"], reverse=True)
        merged = reranked + ranked[settings["reranker_top_n"] :]
        return merged, metadata

    def test(self):
        settings = self.settings()
        if not settings["reranker_enabled"] or settings["reranker_provider"] == "none":
            return {"ok": True, "enabled": settings["reranker_enabled"], "provider": settings["reranker_provider"], "message": "Reranker is disabled."}
        diagnostic_settings = dict(settings)
        diagnostic_settings["reranker_timeout_ms"] = max(settings["reranker_timeout_ms"], 30000)
        sample = [
            {
                "memory_id": 1,
                "title": "PostgreSQL deployment",
                "memory_type": "technical_notes",
                "tags": ["database", "deployment"],
                "summary": "Production deployments use PostgreSQL.",
                "content": "Production deployments use PostgreSQL for durable storage.",
            },
            {
                "memory_id": 2,
                "title": "Camera settings",
                "memory_type": "vision",
                "tags": ["camera"],
                "summary": "Camera snapshots are optional.",
                "content": "Camera snapshots can be enabled from Settings.",
            },
        ]
        started = perf_counter()
        try:
            if settings["reranker_provider"] == "cross_encoder":
                fake = [{"memory": _SampleMemory(item), "semantic_score": 0.5, "trust_score": 0.5, "importance_score": 0.5} for item in sample]
                scores, reasons = self._run_with_timeout(
                    lambda: self._cross_encoder_scores("Which memory discusses database deployment?", fake, diagnostic_settings, wait_for_model=True),
                    diagnostic_settings,
                )
            elif settings["reranker_provider"] == "ollama":
                scores, reasons = self._run_with_timeout(
                    lambda: OllamaRerankerService().rerank("Which memory discusses database deployment?", sample, diagnostic_settings),
                    diagnostic_settings,
                )
            else:
                return {"ok": True, "provider": settings["reranker_provider"], "message": "No provider selected."}
        except Exception as exc:
            return {
                "ok": False,
                "provider": settings["reranker_provider"],
                "model": self._model_name(settings),
                "configured_search_timeout_ms": settings["reranker_timeout_ms"],
                "diagnostic_timeout_ms": diagnostic_settings["reranker_timeout_ms"],
                "error": str(exc),
            }
        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        warning = None
        if elapsed_ms > settings["reranker_timeout_ms"]:
            warning = (
                f"Diagnostic took {elapsed_ms} ms, which is above the configured search timeout "
                f"of {settings['reranker_timeout_ms']} ms. Search will fail open unless you raise Timeout MS or use conditional mode."
            )
        return {
            "ok": True,
            "provider": settings["reranker_provider"],
            "model": self._model_name(settings),
            "elapsed_ms": elapsed_ms,
            "configured_search_timeout_ms": settings["reranker_timeout_ms"],
            "diagnostic_timeout_ms": diagnostic_settings["reranker_timeout_ms"],
            "warning": warning,
            "scores": scores,
            "reasons": reasons,
        }

    def _should_rerank(self, settings, ranked, payload, mode):
        if not settings["reranker_enabled"]:
            return False
        if settings["reranker_provider"] not in {"cross_encoder", "ollama"}:
            return False
        if not ranked or settings["reranker_default_mode"] == "off":
            return False
        if settings["reranker_default_mode"] == "always":
            return True
        if len(ranked) == 1:
            return ranked[0]["semantic_score"] < 0.55
        gap = ranked[0]["semantic_score"] - ranked[1]["semantic_score"]
        if gap <= settings["reranker_conditional_threshold"]:
            return True
        if ranked[0]["semantic_score"] < 0.55:
            return True
        query_kind = (payload.get("query_kind") or payload.get("mode") or mode or "").lower()
        if query_kind in {"context", "context_building"} and int(payload.get("top_k", 1)) > 1:
            return True
        return False

    def _skip_reason(self, settings, ranked):
        if not settings["reranker_enabled"]:
            return "disabled"
        if settings["reranker_provider"] == "none":
            return "provider_none"
        if settings["reranker_default_mode"] == "off":
            return "mode_off"
        if not ranked:
            return "no_candidates"
        return "not_ambiguous"

    def _cross_encoder_scores(self, query, candidates, settings, wait_for_model=False):
        model = self._cross_encoder_model(settings, wait=wait_for_model)
        pairs = [[query, self._candidate_text(item["memory"], settings["reranker_max_text_chars"])] for item in candidates]
        raw_scores = list(model.predict(pairs))
        normalized = self._normalize_scores(raw_scores)
        scores = {}
        for item, score in zip(candidates, normalized):
            scores[item["memory"].id] = score
        return scores, {}

    def _normalize_scores(self, raw_scores):
        values = [float(score) for score in raw_scores]
        if not values:
            return []
        if len(values) == 1:
            value = max(-50.0, min(50.0, values[0]))
            return [1 / (1 + math.exp(-value))]
        low = min(values)
        high = max(values)
        if abs(high - low) < 1e-9:
            return [0.5 for _ in values]
        return [max(0.0, min(1.0, (value - low) / (high - low))) for value in values]

    def _cross_encoder_ready(self, settings):
        key = (settings["reranker_cross_encoder_model"], settings["reranker_device"])
        cls = self.__class__
        with cls._cross_encoder_lock:
            if cls._cross_encoder is not None and cls._cross_encoder_key == key:
                return True
            if cls._cross_encoder_future is not None and cls._cross_encoder_future_key == key:
                if cls._cross_encoder_future.done():
                    cls._cross_encoder = cls._cross_encoder_future.result()
                    cls._cross_encoder_key = key
                    cls._cross_encoder_future = None
                    cls._cross_encoder_future_key = None
                    return True
                return False
            cls._cross_encoder_future = cls._cross_encoder_loader.submit(self._load_cross_encoder, key)
            cls._cross_encoder_future_key = key
            return False

    def _cross_encoder_model(self, settings, wait=False):
        key = (settings["reranker_cross_encoder_model"], settings["reranker_device"])
        cls = self.__class__
        with cls._cross_encoder_lock:
            if cls._cross_encoder is not None and cls._cross_encoder_key == key:
                return cls._cross_encoder
            if cls._cross_encoder_future is None or cls._cross_encoder_future_key != key:
                cls._cross_encoder_future = cls._cross_encoder_loader.submit(self._load_cross_encoder, key)
                cls._cross_encoder_future_key = key
            future = cls._cross_encoder_future
        if not wait and not future.done():
            raise RuntimeError("Cross-encoder model is still loading")
        model = future.result()
        with cls._cross_encoder_lock:
            cls._cross_encoder = model
            cls._cross_encoder_key = key
            cls._cross_encoder_future = None
            cls._cross_encoder_future_key = None
        return model

    def _load_cross_encoder(self, key):
        from sentence_transformers import CrossEncoder

        return CrossEncoder(key[0], device=key[1])

    def _run_with_timeout(self, func, settings):
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(func)
        try:
            return future.result(timeout=max(settings["reranker_timeout_ms"] / 1000, 0.001))
        except TimeoutError as exc:
            future.cancel()
            raise RuntimeError("Reranker timed out") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _candidate_payload(self, memory, max_chars):
        return {
            "memory_id": memory.id,
            "title": memory.title,
            "memory_type": memory.memory_type,
            "tags": memory.tags or [],
            "summary": memory.summary or "",
            "content": (memory.content or "")[:max_chars],
        }

    def _candidate_text(self, memory, max_chars):
        tags = ", ".join(memory.tags or [])
        return (
            f"Title: {memory.title}\n"
            f"Type: {memory.memory_type}\n"
            f"Tags: {tags}\n"
            f"Summary: {memory.summary or ''}\n"
            f"Content: {(memory.content or '')[:max_chars]}"
        )

    def _final_score(self, item, settings):
        weights = {
            "reranker": settings["reranker_weight"],
            "faiss": settings["faiss_weight"],
            "trust": settings["trust_weight"],
            "importance": settings["importance_weight"],
        }
        total = sum(weights.values()) or 1.0
        score = (
            item.get("reranker_score", 0.0) * weights["reranker"]
            + item.get("semantic_score", 0.0) * weights["faiss"]
            + item["memory"].trust_score * weights["trust"]
            + item["memory"].importance_score * weights["importance"]
        ) / total
        return max(0.0, min(1.0, score))

    def _model_name(self, settings):
        if settings["reranker_provider"] == "cross_encoder":
            return settings["reranker_cross_encoder_model"]
        if settings["reranker_provider"] == "ollama":
            return settings["reranker_ollama_model"]
        return None


class _SampleMemory:
    def __init__(self, payload):
        self.id = payload["memory_id"]
        self.title = payload["title"]
        self.memory_type = payload["memory_type"]
        self.tags = payload["tags"]
        self.summary = payload["summary"]
        self.content = payload["content"]
