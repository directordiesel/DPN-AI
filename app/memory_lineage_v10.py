from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from app.advanced_layered_memory_v10 import (
    AdvancedLayeredMemory,
    KnowledgeClass,
    MemoryLayer,
    MemoryProvenance,
    MemoryWriteRequest,
)
from app.memory_scope import ScopedMemory


class MemoryLineageError(ValueError):
    """Raised when a memory promotion/supersession request cannot be trusted."""


@dataclass(frozen=True)
class MemorySupersessionRequest:
    replacement: MemoryWriteRequest
    supersedes_memory_ids: tuple[str, ...]
    reason: str
    sensitive: bool = False


class MemoryLineageService:
    """Evidence-gated, non-destructive memory promotion and supersession.

    Supersession never edits or deletes prior memories. The replacement is written
    through AdvancedLayeredMemory and a durable procedural lineage receipt is then
    stored in the same scope. Callers can audit both the old version and the decision
    that a newer version should be preferred.
    """

    MAX_SUPERSEDED = 32
    MAX_REASON_CHARS = 1_000

    def __init__(self, memory: AdvancedLayeredMemory) -> None:
        self.memory = memory

    @staticmethod
    def _clean(value: str | None) -> str:
        return (value or "").strip()

    @staticmethod
    def _metadata(item: dict[str, Any]) -> dict[str, Any]:
        return dict(item.get("metadata") or {})

    def _load_versions(self, scope_id: str, layer: MemoryLayer, logical_key: str) -> dict[str, dict[str, Any]]:
        try:
            items = self.memory.memory_service.db.list_semantic_items(scope_id, limit=5000)
        except Exception as exc:  # noqa: BLE001
            raise MemoryLineageError("existing memory versions could not be verified") from exc
        versions: dict[str, dict[str, Any]] = {}
        for item in items:
            metadata = self._metadata(item)
            if metadata.get("v10_memory_schema") != 1:
                continue
            if metadata.get("v10_layer") != layer.value:
                continue
            if metadata.get("v10_logical_key") != logical_key:
                continue
            memory_id = self._clean(str(item.get("id") or ""))
            if memory_id:
                versions[memory_id] = item
        return versions

    @staticmethod
    def _authority(item: dict[str, Any]) -> float:
        provenance = dict((item.get("metadata") or {}).get("v10_provenance") or {})
        try:
            return float(provenance.get("authority") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    async def supersede(self, request: MemorySupersessionRequest) -> dict[str, Any]:
        reason = self._clean(request.reason)
        if not reason:
            return {"ok": False, "error": "supersession reason is required", "stored": False}
        if len(reason) > self.MAX_REASON_CHARS:
            return {"ok": False, "error": "supersession reason exceeds limit", "stored": False}

        targets = tuple(self._clean(value) for value in request.supersedes_memory_ids)
        if not targets or any(not value for value in targets):
            return {"ok": False, "error": "at least one superseded memory id is required", "stored": False}
        if len(targets) != len(set(targets)):
            return {"ok": False, "error": "superseded memory ids must be unique", "stored": False}
        if len(targets) > self.MAX_SUPERSEDED:
            return {"ok": False, "error": "superseded memory id limit exceeded", "stored": False}

        replacement = request.replacement
        try:
            layer, _knowledge_class, scope, scope_id, content = self.memory._validate_request(replacement)
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc), "stored": False}
        if layer == MemoryLayer.WORKING:
            return {"ok": False, "error": "working memory cannot participate in durable supersession", "stored": False}
        if not replacement.provenance.evidence_ids:
            return {"ok": False, "error": "memory supersession requires evidence ids", "stored": False}

        logical_key = self.memory._logical_key(replacement.key)
        try:
            versions = self._load_versions(scope_id, layer, logical_key)
        except MemoryLineageError as exc:
            return {"ok": False, "error": str(exc), "stored": False}
        missing = sorted(target for target in targets if target not in versions)
        if missing:
            return {"ok": False, "error": "supersession target is missing from the exact memory lineage", "stored": False, "missing_memory_ids": missing}

        replacement_content = self._clean(content)
        if any(self._clean(str(versions[target].get("content") or "")) == replacement_content for target in targets):
            return {"ok": False, "error": "replacement must differ from every superseded version", "stored": False}

        target_authority = max(self._authority(versions[target]) for target in targets)
        if float(replacement.provenance.authority) < target_authority:
            return {
                "ok": False,
                "error": "replacement authority cannot be lower than the superseded version",
                "stored": False,
                "required_authority": target_authority,
            }

        # AdvancedLayeredMemory delegates durable storage to MemoryService. Predict
        # the exact durable ID using that same ScopedMemory identity function so the
        # lineage evidence bound can be checked before the replacement is written.
        content_hash = self.memory._content_hash(replacement_content)
        physical_key = f"v10:{layer.value}:{logical_key}:{content_hash[:16]}"
        predicted_replacement_id = ScopedMemory.build(
            physical_key,
            replacement_content,
            scope=scope,
            source="lineage-preflight",
            **self.memory._scope_kwargs(replacement.context),
        ).memory_id
        lineage_evidence = tuple(
            dict.fromkeys((*replacement.provenance.evidence_ids, predicted_replacement_id, *sorted(targets)))
        )
        if len(lineage_evidence) > self.memory.MAX_EVIDENCE_IDS:
            return {"ok": False, "error": "supersession lineage evidence id limit exceeded", "stored": False}

        replacement_sensitive = bool(request.sensitive or replacement.sensitive)
        if replacement_sensitive != bool(replacement.sensitive):
            replacement = MemoryWriteRequest(
                layer=replacement.layer,
                key=replacement.key,
                content=replacement.content,
                knowledge_class=replacement.knowledge_class,
                provenance=replacement.provenance,
                context=replacement.context,
                scope=replacement.scope,
                ttl_seconds=replacement.ttl_seconds,
                sensitive=True,
            )

        replacement_result = await self.memory.remember(replacement)
        if not replacement_result.get("ok"):
            return {
                "ok": False,
                "error": replacement_result.get("error") or "replacement memory write failed",
                "stored": False,
                "phase": "replacement",
            }
        replacement_id = self._clean(str(replacement_result.get("memory_id") or ""))
        if not replacement_id:
            return {"ok": False, "error": "replacement memory id is missing", "stored": False, "phase": "replacement"}
        if replacement_id in targets:
            return {"ok": False, "error": "replacement cannot supersede itself", "stored": False, "phase": "replacement"}
        if replacement_id != predicted_replacement_id:
            return {
                "ok": False,
                "error": "replacement memory identity disagrees with deterministic lineage identity",
                "stored": False,
                "phase": "replacement",
                "partial_persistence": True,
            }

        receipt_payload = {
            "schema_version": 1,
            "decision": "supersedes",
            "layer": layer.value,
            "logical_key": logical_key,
            "replacement_memory_id": replacement_id,
            "superseded_memory_ids": sorted(targets),
            "reason": reason,
        }
        receipt_content = json.dumps(receipt_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        receipt = MemoryWriteRequest(
            layer=MemoryLayer.PROCEDURAL,
            key=f"supersession:{layer.value}:{logical_key}:{replacement_id}",
            content=receipt_content,
            knowledge_class=KnowledgeClass.DERIVED,
            provenance=MemoryProvenance(
                source_type="memory_supersession",
                source_id=replacement_id,
                evidence_ids=lineage_evidence,
                confidence=replacement.provenance.confidence,
                authority=replacement.provenance.authority,
            ),
            context=replacement.context,
            scope=scope,
            sensitive=replacement_sensitive,
        )
        receipt_result = await self.memory.remember(receipt)
        if not receipt_result.get("ok"):
            return {
                "ok": False,
                "error": receipt_result.get("error") or "supersession receipt write failed",
                "stored": False,
                "phase": "lineage_receipt",
                "replacement_memory_id": replacement_id,
                "partial_persistence": True,
            }
        return {
            "ok": True,
            "stored": True,
            "replacement_memory_id": replacement_id,
            "superseded_memory_ids": sorted(targets),
            "lineage_receipt_memory_id": receipt_result.get("memory_id"),
            "scope_id": scope_id,
            "layer": layer.value,
            "logical_key": logical_key,
            "conflict_preserved": True,
            "destructive_mutation": False,
        }


__all__ = ["MemoryLineageError", "MemoryLineageService", "MemorySupersessionRequest"]
