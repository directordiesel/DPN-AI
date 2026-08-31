from __future__ import annotations

import re
from typing import Any

from app.db import Database


class KnowledgeGraph:
    """Provenance-aware local graph memory for projects, entities, facts, and decisions."""

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _clean(value: str, limit: int = 500) -> str:
        return re.sub(r"\s+", " ", str(value)).strip()[:limit]

    def add_node(self, label: str, node_type: str = "entity", data: dict[str, Any] | None = None,
                 confidence: float = 1.0, source: str = "manual", project_id: str | None = None,
                 node_id: str | None = None) -> dict[str, Any]:
        label = self._clean(label)
        if not label:
            return {"ok": False, "error": "Node label is required"}
        node = self.db.upsert_graph_node(
            node_id=node_id, label=label, node_type=self._clean(node_type, 80) or "entity",
            data=data or {}, confidence=max(0.0, min(float(confidence), 1.0)),
            source=self._clean(source, 1000), project_id=project_id,
        )
        return {"ok": True, "node": node}

    def add_edge(self, source_id: str, relation: str, target_id: str, data: dict[str, Any] | None = None,
                 confidence: float = 1.0, source: str = "manual") -> dict[str, Any]:
        if not self.db.get_graph_node(source_id) or not self.db.get_graph_node(target_id):
            return {"ok": False, "error": "Both source and target nodes must exist"}
        relation = self._clean(relation, 120)
        if not relation:
            return {"ok": False, "error": "Relation is required"}
        edge = self.db.add_graph_edge(source_id, relation, target_id, data or {}, max(0.0, min(float(confidence), 1.0)), self._clean(source, 1000))
        return {"ok": True, "edge": edge}

    def remember_fact(self, subject: str, relation: str, object_value: str, source: str = "manual",
                      confidence: float = 0.8, project_id: str | None = None,
                      metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        subject_result = self.add_node(subject, "entity", project_id=project_id, source=source, confidence=confidence)
        object_result = self.add_node(object_value, "entity", project_id=project_id, source=source, confidence=confidence)
        if not subject_result.get("ok") or not object_result.get("ok"):
            return {"ok": False, "error": "Unable to create fact nodes"}
        edge_result = self.add_edge(
            subject_result["node"]["id"], relation, object_result["node"]["id"],
            data=metadata or {}, confidence=confidence, source=source,
        )
        return {
            "ok": bool(edge_result.get("ok")), "subject": subject_result["node"],
            "object": object_result["node"], "edge": edge_result.get("edge"),
        }

    def ingest_triples(self, triples: list[dict[str, Any]], source: str = "agent",
                       project_id: str | None = None) -> dict[str, Any]:
        added = []
        failed = []
        for triple in triples[:500]:
            result = self.remember_fact(
                str(triple.get("subject", "")), str(triple.get("relation", "")),
                str(triple.get("object", "")), source=str(triple.get("source") or source),
                confidence=float(triple.get("confidence", 0.75)), project_id=project_id,
                metadata=triple.get("metadata") if isinstance(triple.get("metadata"), dict) else {},
            )
            (added if result.get("ok") else failed).append(result)
        return {"ok": not failed, "added": len(added), "failed": len(failed), "results": added[:100], "errors": failed[:20]}

    def search(self, query: str, project_id: str | None = None, limit: int = 30) -> dict[str, Any]:
        return {"ok": True, "nodes": self.db.search_graph_nodes(query, project_id, limit)}

    def neighborhood(self, node_id: str, depth: int = 1, limit: int = 100) -> dict[str, Any]:
        node = self.db.get_graph_node(node_id)
        if not node:
            return {"ok": False, "error": "Node not found"}
        return {"ok": True, "node": node, "graph": self.db.graph_neighborhood(node_id, depth, limit)}

    def stats(self) -> dict[str, Any]:
        return {"ok": True, **self.db.graph_stats()}