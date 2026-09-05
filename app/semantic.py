from __future__ import annotations

import hashlib
import math
from typing import Any, Iterable

from app.db import Database
from app.ollama_client import OllamaClient


class SemanticMemory:
    def __init__(self, db: Database, ollama: OllamaClient, embedding_model: str):
        self.db = db
        self.ollama = ollama
        self.embedding_model = embedding_model

    async def add(self, content: str, namespace: str = "global", source: str = "manual",
                  metadata: dict[str, Any] | None = None, item_id: str | None = None) -> dict[str, Any]:
        content = content.strip()
        if not content:
            return {"ok": False, "error": "Content is empty"}
        namespace = (namespace or "global").strip() or "global"
        vectors = await self.ollama.embed(self.embedding_model, [content])
        if not vectors:
            return {"ok": False, "error": "Embedding model returned no vector"}
        item_id = item_id or hashlib.sha256(f"{namespace}\0{source}\0{content}".encode()).hexdigest()[:32]
        item = self.db.upsert_semantic_item(item_id, namespace, source, content, vectors[0], metadata)
        return {"ok": True, "item": {k: v for k, v in item.items() if k != "vector"}, "dimensions": len(vectors[0])}

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0

    @staticmethod
    def _normalize_namespaces(namespaces: Iterable[str]) -> list[str]:
        output: list[str] = []
        seen: set[str] = set()
        for namespace in namespaces:
            value = (namespace or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            output.append(value)
        return output

    async def search_many(self, query: str, namespaces: Iterable[str], limit: int = 8) -> dict[str, Any]:
        query = (query or "").strip()
        normalized_namespaces = self._normalize_namespaces(namespaces)
        if not query:
            return {"ok": False, "error": "Query is empty", "results": []}
        if not normalized_namespaces:
            return {"ok": False, "error": "At least one namespace is required", "results": []}

        vectors = await self.ollama.embed(self.embedding_model, [query])
        if not vectors:
            return {"ok": False, "error": "Embedding model returned no vector", "results": []}
        query_vector = vectors[0]
        scored: list[dict[str, Any]] = []
        for namespace in normalized_namespaces:
            for item in self.db.list_semantic_items(namespace, limit=5000):
                score = self._cosine(query_vector, item.get("vector", []))
                scored.append({
                    "id": item["id"],
                    "namespace": item["namespace"],
                    "source": item["source"],
                    "content": item["content"],
                    "metadata": item.get("metadata", {}),
                    "score": round(score, 6),
                })
        scored.sort(key=lambda item: (-item["score"], item["namespace"], item["id"]))
        bounded_limit = max(1, min(limit, 50))
        return {
            "ok": True,
            "model": self.embedding_model,
            "namespaces": normalized_namespaces,
            "results": scored[:bounded_limit],
        }

    async def search(self, query: str, namespace: str = "global", limit: int = 8) -> dict[str, Any]:
        result = await self.search_many(query, [namespace], limit=limit)
        if result.get("ok"):
            result["namespace"] = namespace
        return result
