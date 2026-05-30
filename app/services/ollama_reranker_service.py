import json
import urllib.error
import urllib.request


class OllamaRerankerService:
    def rerank(self, query, candidates, settings):
        payload = {
            "model": settings["reranker_ollama_model"],
            "prompt": self._prompt(query, candidates),
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }
        request = urllib.request.Request(
            f"{settings['reranker_ollama_base_url'].rstrip('/')}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        timeout = max(float(settings["reranker_timeout_ms"]) / 1000, 0.001)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama reranker failed: {exc}") from exc

        try:
            ranked = json.loads(body.get("response", "{}")).get("ranked", [])
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Ollama returned invalid reranker JSON") from exc

        valid_ids = {candidate["memory_id"] for candidate in candidates}
        scores = {}
        reasons = {}
        for item in ranked:
            memory_id = item.get("memory_id")
            if memory_id not in valid_ids:
                continue
            try:
                scores[memory_id] = max(0.0, min(1.0, float(item.get("reranker_score", 0))))
            except (TypeError, ValueError):
                continue
            if item.get("reason"):
                reasons[memory_id] = str(item["reason"])[:500]
        return scores, reasons

    def _prompt(self, query, candidates):
        return (
            "You are a reranking engine for an AI memory system.\n"
            "Rank the memories by relevance to the user query.\n"
            "Return JSON only.\n"
            "Do not answer the query.\n"
            "Do not invent data.\n"
            "Do not include explanations unless requested.\n"
            "Use only the provided candidates.\n\n"
            f"Query: {query}\n\n"
            f"Candidates:\n{json.dumps(candidates, ensure_ascii=False)}\n\n"
            "Expected JSON:\n"
            '{"ranked":[{"memory_id":106,"reranker_score":0.95,"reason":"Directly answers the query."}]}'
        )
