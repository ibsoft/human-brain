import logging
import json
import re
import urllib.error
import urllib.request

import numpy as np
from flask import current_app, has_app_context

from app.utils.hash import sha256_json

logger = logging.getLogger(__name__)


class EmbeddingService:
    _model_cache = {}

    def __init__(self, model_name):
        self.model_name = model_name
        self._model = None

    @property
    def model(self):
        if self.model_name == "hash" or self.model_name.startswith("ollama:"):
            self._model = False
            return self._model
        if self.model_name in self._model_cache:
            self._model = self._model_cache[self.model_name]
            return self._model
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                model_name = self.model_name
                if model_name.startswith("sentence-transformers/"):
                    model_name = model_name.removeprefix("sentence-transformers/")
                try:
                    self._model = SentenceTransformer(model_name, local_files_only=True)
                except TypeError:
                    self._model = SentenceTransformer(model_name)
                self._model_cache[self.model_name] = self._model
            except Exception as exc:
                logger.warning("Falling back to deterministic hash embeddings: %s", exc)
                self._model = False
        return self._model

    def embed(self, text):
        if self.model_name.startswith("ollama:"):
            vector = self._embed_ollama(text)
            if vector is not None:
                return vector
        if self.model:
            vector = self.model.encode([text], normalize_embeddings=True, show_progress_bar=False)[0].astype("float32")
        else:
            vector = self._hash_embed(text)
        return vector

    def hash(self, vector):
        return sha256_json([round(float(x), 6) for x in vector.tolist()])

    def _hash_embed(self, text):
        vector = np.zeros(384, dtype="float32")
        tokens = re.findall(r"[a-z0-9][a-z0-9._:/-]+", (text or "").lower())
        synonyms = {
            "online": ["website", "web", "site", "url"],
            "address": ["url", "website", "web", "site"],
            "site": ["website", "url"],
            "website": ["site", "url", "online"],
        }
        expanded = []
        for token in tokens:
            expanded.append(token)
            expanded.extend(synonyms.get(token, []))
        for token in expanded:
            bucket = int.from_bytes(token.encode("utf-8"), "little", signed=False) % len(vector)
            vector[bucket] += 1.0
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector

    def _embed_ollama(self, text):
        model = self.model_name.removeprefix("ollama:").strip()
        base_url = "http://localhost:11434"
        if has_app_context():
            try:
                from app.services.settings_service import SettingsService

                base_url = SettingsService.get("ollama_base_url", base_url)
            except Exception:
                base_url = current_app.config.get("OLLAMA_BASE_URL", base_url)
        payload = json.dumps({"model": model, "prompt": text}).encode("utf-8")
        request = urllib.request.Request(
            f"{str(base_url).rstrip('/')}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            logger.warning("Ollama embedding failed for %s, using hash fallback: %s", model, exc)
            return None
        raw = data.get("embedding") or (data.get("embeddings") or [None])[0]
        if not raw:
            logger.warning("Ollama embedding response did not include a vector, using hash fallback")
            return None
        vector = np.array(raw, dtype="float32")
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector
