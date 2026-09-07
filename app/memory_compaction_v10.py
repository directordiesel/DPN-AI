from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from app.advanced_layered_memory_v10 import AdvancedLayeredMemory, MemoryLayer


class MemoryCompactionError(ValueError):
    """Raised when durable memory lineage cannot be compacted safely."""


@dataclass(frozen=True)
class MemoryCompactionReport:
    scope_id: str
    scanned_items: int
    canonical_items: tuple[str, ...]
    duplicate_groups: tuple[tuple[str, ...], ...]
    superseded_memory_ids: tuple[str, ...]
    preferred_memory_ids: tuple[str, ...]
    invalid_receipt_ids: tuple[str, ...]
    dangling_receipt_ids: tuple[str, ...]
    cycle_memory_ids: tuple[str, ...]
    recovery_required: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "scanned_items": self.scanned_items,
            "canonical_items": list(self.canonical_items),
            "duplicate_groups": [list(group) for group in self.duplicate_groups],
            "superseded_memory_ids": list(self.superseded_memory_ids),
            "preferred_memory_ids": list(self.preferred_memory_ids),
            "invalid_receipt_ids": list(self.invalid_receipt_ids),
            "dangling_receipt_ids": list(self.dangling_receipt_ids),
            "cycle_memory_ids": list(self.cycle_memory_ids),
            "recovery_required": self.recovery_required,
            "destructive_mutation": False,
        }


class MemoryCompactionService:
    """Build a compacted read view without deleting durable history.

    The service treats v10 memories as immutable evidence records. It derives duplicate
    groups from exact content hashes and consumes only validated supersession receipts.
    Invalid, dangling, cross-lineage, or cyclic receipts never affect preferred-memory
    selection and instead surface as recovery findings.
    """

    MAX_SCAN_ITEMS = 5000

    def __init__(self, memory: AdvancedLayeredMemory) -> None:
        self.memory = memory

    @staticmethod
    def _clean(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _metadata(item: dict[str, Any]) -> dict[str, Any]:
        return dict(item.get("metadata") or {})

    @classmethod
    def _lineage_key(cls, item: dict[str, Any]) -> tuple[str, str, str]:
        metadata = cls._metadata(item)
        return (
            cls._clean(item.get("namespace")),
            cls._clean(metadata.get("v10_layer")),
            cls._clean(metadata.get("v10_logical_key")),
        )

    def _load(self, scope_id: str) -> list[dict[str, Any]]:
        try:
            items = self.memory.memory_service.db.list_semantic_items(scope_id, limit=self.MAX_SCAN_ITEMS)
        except Exception as exc:  # noqa: BLE001
            raise MemoryCompactionError("durable memory could not be inspected") from exc
        return [dict(item) for item in items]

    @staticmethod
    def _parse_receipt(item: dict[str, Any]) -> dict[str, Any] | None:
        metadata = dict(item.get("metadata") or {})
        provenance = dict(metadata.get("v10_provenance") or {})
        if metadata.get("v10_memory_schema") != 1:
            return None
        if metadata.get("v10_layer") != MemoryLayer.PROCEDURAL.value:
            return None
        if provenance.get("source_type") != "memory_supersession":
            return None
        try:
            payload = json.loads(str(item.get("content") or ""))
        except json.JSONDecodeError:
            return {"invalid": True}
        return payload if isinstance(payload, dict) else {"invalid": True}

    def analyze(self, scope_id: str) -> MemoryCompactionReport:
        scope_id = self._clean(scope_id)
        if not scope_id:
            raise MemoryCompactionError("scope_id is required")
        items = self._load(scope_id)
        v10_items = [item for item in items if self._metadata(item).get("v10_memory_schema") == 1]
        by_id = {self._clean(item.get("id")): item for item in v10_items if self._clean(item.get("id"))}

        duplicate_map: dict[tuple[str, str, str, str], list[str]] = {}
        canonical_ids: list[str] = []
        for memory_id, item in by_id.items():
            metadata = self._metadata(item)
            if metadata.get("v10_layer") == MemoryLayer.PROCEDURAL.value and dict(metadata.get("v10_provenance") or {}).get("source_type") == "memory_supersession":
                continue
            content_hash = self._clean(metadata.get("v10_content_hash"))
            if not content_hash:
                content_hash = self.memory._content_hash(self._clean(item.get("content")))
            key = (*self._lineage_key(item), content_hash)
            duplicate_map.setdefault(key, []).append(memory_id)

        duplicate_groups: list[tuple[str, ...]] = []
        canonical_for: dict[str, str] = {}
        for _key, ids in sorted(duplicate_map.items()):
            ordered = sorted(ids)
            canonical = ordered[0]
            canonical_ids.append(canonical)
            for memory_id in ordered:
                canonical_for[memory_id] = canonical
            if len(ordered) > 1:
                duplicate_groups.append(tuple(ordered))

        invalid_receipts: list[str] = []
        dangling_receipts: list[str] = []
        edges: dict[str, set[str]] = {}
        superseded: set[str] = set()

        for receipt_id, item in by_id.items():
            payload = self._parse_receipt(item)
            if payload is None:
                continue
            if payload.get("invalid"):
                invalid_receipts.append(receipt_id)
                continue
            if payload.get("schema_version") != 1 or payload.get("decision") != "supersedes":
                invalid_receipts.append(receipt_id)
                continue
            replacement_id = self._clean(payload.get("replacement_memory_id"))
            target_ids = payload.get("superseded_memory_ids")
            if not replacement_id or not isinstance(target_ids, list) or not target_ids:
                invalid_receipts.append(receipt_id)
                continue
            targets = [self._clean(value) for value in target_ids]
            if any(not value for value in targets) or len(targets) != len(set(targets)):
                invalid_receipts.append(receipt_id)
                continue
            replacement = by_id.get(replacement_id)
            target_items = [by_id.get(target) for target in targets]
            if replacement is None or any(item is None for item in target_items):
                dangling_receipts.append(receipt_id)
                continue
            expected = (
                scope_id,
                self._clean(payload.get("layer")),
                self._clean(payload.get("logical_key")),
            )
            if self._lineage_key(replacement) != expected or any(self._lineage_key(target) != expected for target in target_items if target is not None):
                invalid_receipts.append(receipt_id)
                continue
            replacement_canonical = canonical_for.get(replacement_id, replacement_id)
            for target_id in targets:
                target_canonical = canonical_for.get(target_id, target_id)
                if target_canonical == replacement_canonical:
                    invalid_receipts.append(receipt_id)
                    break
            else:
                for target_id in targets:
                    target_canonical = canonical_for.get(target_id, target_id)
                    edges.setdefault(target_canonical, set()).add(replacement_canonical)
                    superseded.add(target_canonical)

        cycle_nodes: set[str] = set()
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str, stack: list[str]) -> None:
            if node in visited:
                return
            if node in visiting:
                if node in stack:
                    cycle_nodes.update(stack[stack.index(node):])
                return
            visiting.add(node)
            stack.append(node)
            for nxt in sorted(edges.get(node, set())):
                visit(nxt, stack)
            stack.pop()
            visiting.discard(node)
            visited.add(node)

        for node in sorted(set(canonical_ids) | set(edges)):
            visit(node, [])

        if cycle_nodes:
            superseded.difference_update(cycle_nodes)

        preferred = sorted(memory_id for memory_id in set(canonical_ids) if memory_id not in superseded)
        recovery_required = bool(invalid_receipts or dangling_receipts or cycle_nodes)
        return MemoryCompactionReport(
            scope_id=scope_id,
            scanned_items=len(items),
            canonical_items=tuple(sorted(set(canonical_ids))),
            duplicate_groups=tuple(sorted(duplicate_groups)),
            superseded_memory_ids=tuple(sorted(superseded)),
            preferred_memory_ids=tuple(preferred),
            invalid_receipt_ids=tuple(sorted(set(invalid_receipts))),
            dangling_receipt_ids=tuple(sorted(set(dangling_receipts))),
            cycle_memory_ids=tuple(sorted(cycle_nodes)),
            recovery_required=recovery_required,
        )


__all__ = ["MemoryCompactionError", "MemoryCompactionReport", "MemoryCompactionService"]
