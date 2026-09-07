from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import math
import re
import time
from typing import Any, Callable, Iterable

from app.memory_scope import MemoryScope, ScopedMemory
from app.memory_service import MemoryService


class MemoryLayer(str, Enum):
    WORKING = "working"
    CONVERSATION = "conversation"
    PROJECT = "project"
    ORGANIZATION = "organization"
    USER = "user"
    PROCEDURAL = "procedural"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"


class KnowledgeClass(str, Enum):
    OBSERVATION = "observation"
    FACT = "fact"
    DERIVED = "derived"
    INFERENCE = "inference"
    PROCEDURE = "procedure"
    EPISODE = "episode"


@dataclass(frozen=True)
class MemoryContext:
    organization_id: str | None = None
    user_id: str | None = None
    project_id: str | None = None
    conversation_id: str | None = None


@dataclass(frozen=True)
class MemoryProvenance:
    source_type: str
    source_id: str
    evidence_ids: tuple[str, ...] = ()
    confidence: float = 1.0
    authority: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "evidence_ids": list(self.evidence_ids),
            "confidence": self.confidence,
            "authority": self.authority,
        }


@dataclass(frozen=True)
class MemoryWriteRequest:
    layer: MemoryLayer | str
    key: str
    content: str
    knowledge_class: KnowledgeClass | str
    provenance: MemoryProvenance
    context: MemoryContext = field(default_factory=MemoryContext)
    scope: MemoryScope | str | None = None
    ttl_seconds: int | None = None
    sensitive: bool = False


@dataclass(frozen=True)
class WorkingMemoryEntry:
    memory_id: str
    layer: MemoryLayer
    scope_id: str
    logical_key: str
    content: str
    knowledge_class: KnowledgeClass
    provenance: MemoryProvenance
    created_at: float
    expires_at: float | None

    def to_result(self, score: float, *, conflict: bool = False) -> dict[str, Any]:
        return {
            "id": self.memory_id,
            "namespace": self.scope_id,
            "source": f"v10:{self.provenance.source_type}:{self.provenance.source_id}",
            "content": self.content,
            "metadata": {
                "v10_memory_schema": 1,
                "v10_layer": self.layer.value,
                "v10_logical_key": self.logical_key,
                "v10_knowledge_class": self.knowledge_class.value,
                "v10_provenance": self.provenance.to_dict(),
                "v10_created_at": self.created_at,
                "v10_expires_at": self.expires_at,
                "v10_persistent": False,
            },
            "score": round(score, 6),
            "conflict": conflict,
        }


class AdvancedLayeredMemory:
    """v10 policy and orchestration layer over the existing memory/semantic store.

    The runtime intentionally does not introduce a second persistence engine.
    Durable writes delegate to MemoryService while this layer adds typed memory
    layers, organization/user isolation, provenance, version preservation,
    conflict reporting, retention, bounded working memory, and ranked recall.
    """

    MAX_KEY_CHARS = 256
    MAX_CONTENT_CHARS = 20_000
    MAX_EVIDENCE_IDS = 128
    MAX_TTL_SECONDS = 10 * 365 * 24 * 60 * 60
    MAX_RECALL_LIMIT = 50
    PERSISTENT_LAYERS = frozenset(layer for layer in MemoryLayer if layer != MemoryLayer.WORKING)

    _TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")

    def __init__(
        self,
        memory_service: MemoryService,
        *,
        approval_guard: Callable[[MemoryWriteRequest], bool] | None = None,
        clock: Callable[[], float] = time.time,
        max_working_items: int = 128,
    ):
        self.memory_service = memory_service
        self.approval_guard = approval_guard
        self.clock = clock
        self.max_working_items = max(1, min(int(max_working_items), 2048))
        self._working: dict[str, WorkingMemoryEntry] = {}

    @staticmethod
    def _clean(value: str | None) -> str:
        return (value or "").strip()

    @classmethod
    def _logical_key(cls, key: str) -> str:
        return cls._clean(key).lower()

    @staticmethod
    def _content_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _memory_id(scope_id: str, layer: MemoryLayer, logical_key: str, content_hash: str) -> str:
        raw = f"v10\0{scope_id}\0{layer.value}\0{logical_key}\0{content_hash}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _scope_kwargs(context: MemoryContext) -> dict[str, str | None]:
        return {
            "organization_id": context.organization_id,
            "user_id": context.user_id,
            "project_id": context.project_id,
            "conversation_id": context.conversation_id,
        }

    @staticmethod
    def _most_specific_scope(context: MemoryContext, *, include_conversation: bool = True) -> MemoryScope:
        if include_conversation and AdvancedLayeredMemory._clean(context.conversation_id):
            return MemoryScope.CONVERSATION
        if AdvancedLayeredMemory._clean(context.project_id):
            return MemoryScope.PROJECT
        if AdvancedLayeredMemory._clean(context.user_id):
            return MemoryScope.USER
        if AdvancedLayeredMemory._clean(context.organization_id):
            return MemoryScope.ORGANIZATION
        return MemoryScope.GLOBAL

    def _resolve_scope(self, request: MemoryWriteRequest, layer: MemoryLayer) -> MemoryScope:
        explicit = MemoryScope(request.scope) if request.scope is not None else None
        forced: dict[MemoryLayer, MemoryScope] = {
            MemoryLayer.CONVERSATION: MemoryScope.CONVERSATION,
            MemoryLayer.PROJECT: MemoryScope.PROJECT,
            MemoryLayer.ORGANIZATION: MemoryScope.ORGANIZATION,
            MemoryLayer.USER: MemoryScope.USER,
        }
        if layer in forced:
            resolved = forced[layer]
            if explicit is not None and explicit != resolved:
                raise ValueError(f"{layer.value} layer requires {resolved.value} scope")
            return resolved
        if explicit is not None:
            return explicit
        if layer == MemoryLayer.SEMANTIC:
            return self._most_specific_scope(request.context, include_conversation=False)
        return self._most_specific_scope(request.context)

    def _validate_request(self, request: MemoryWriteRequest) -> tuple[MemoryLayer, KnowledgeClass, MemoryScope, str, str]:
        layer = MemoryLayer(request.layer)
        knowledge_class = KnowledgeClass(request.knowledge_class)
        key = self._clean(request.key)
        content = self._clean(request.content)
        if not key:
            raise ValueError("memory key is required")
        if len(key) > self.MAX_KEY_CHARS:
            raise ValueError("memory key exceeds limit")
        if not content:
            raise ValueError("memory content is required")
        if len(content) > self.MAX_CONTENT_CHARS:
            raise ValueError("memory content exceeds limit")

        provenance = request.provenance
        source_type = self._clean(provenance.source_type)
        source_id = self._clean(provenance.source_id)
        if not source_type or not source_id:
            raise ValueError("memory provenance requires source_type and source_id")
        if not math.isfinite(provenance.confidence) or not 0.0 <= provenance.confidence <= 1.0:
            raise ValueError("memory provenance confidence must be between 0 and 1")
        if not math.isfinite(provenance.authority) or not 0.0 <= provenance.authority <= 1.0:
            raise ValueError("memory provenance authority must be between 0 and 1")
        evidence_ids = [self._clean(item) for item in provenance.evidence_ids]
        if any(not item for item in evidence_ids):
            raise ValueError("memory provenance evidence ids cannot be empty")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("memory provenance evidence ids must be unique")
        if len(evidence_ids) > self.MAX_EVIDENCE_IDS:
            raise ValueError("memory provenance evidence id limit exceeded")
        if knowledge_class in {KnowledgeClass.DERIVED, KnowledgeClass.INFERENCE} and not evidence_ids:
            raise ValueError(f"{knowledge_class.value} memory requires evidence ids")

        if request.ttl_seconds is not None:
            if not isinstance(request.ttl_seconds, int) or isinstance(request.ttl_seconds, bool):
                raise ValueError("ttl_seconds must be an integer")
            if request.ttl_seconds <= 0 or request.ttl_seconds > self.MAX_TTL_SECONDS:
                raise ValueError("ttl_seconds is outside the allowed range")

        scope = self._resolve_scope(request, layer)
        # Resolving the namespace here validates every required scope identifier
        # before any working-memory or durable mutation occurs.
        scope_id = ScopedMemory.scope_id(scope, **self._scope_kwargs(request.context))
        return layer, knowledge_class, scope, scope_id, content

    def _purge_expired_working(self, now: float) -> None:
        expired = [
            memory_id
            for memory_id, entry in self._working.items()
            if entry.expires_at is not None and entry.expires_at <= now
        ]
        for memory_id in expired:
            self._working.pop(memory_id, None)

    def _enforce_working_bound(self) -> None:
        while len(self._working) > self.max_working_items:
            victim = min(self._working.values(), key=lambda item: (item.created_at, item.memory_id))
            self._working.pop(victim.memory_id, None)

    def _existing_versions(self, scope_id: str, layer: MemoryLayer, logical_key: str, now: float) -> list[dict[str, Any]]:
        items = self.memory_service.db.list_semantic_items(scope_id, limit=5000)
        output: list[dict[str, Any]] = []
        for item in items:
            metadata = dict(item.get("metadata") or {})
            if metadata.get("v10_memory_schema") != 1:
                continue
            if metadata.get("v10_layer") != layer.value:
                continue
            if metadata.get("v10_logical_key") != logical_key:
                continue
            expires_at = metadata.get("v10_expires_at")
            if isinstance(expires_at, (int, float)) and expires_at <= now:
                continue
            output.append(item)
        return output

    async def remember(self, request: MemoryWriteRequest) -> dict[str, Any]:
        try:
            layer, knowledge_class, scope, scope_id, content = self._validate_request(request)
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc), "stored": False}

        if request.sensitive and layer in self.PERSISTENT_LAYERS:
            if self.approval_guard is None:
                return {"ok": False, "error": "sensitive persistent memory requires approval", "stored": False}
            try:
                approved = bool(self.approval_guard(request))
            except Exception:
                approved = False
            if not approved:
                return {"ok": False, "error": "sensitive persistent memory approval denied", "stored": False}

        now = float(self.clock())
        expires_at = now + request.ttl_seconds if request.ttl_seconds is not None else None
        logical_key = self._logical_key(request.key)
        content_hash = self._content_hash(content)
        memory_id = self._memory_id(scope_id, layer, logical_key, content_hash)

        if layer == MemoryLayer.WORKING:
            self._purge_expired_working(now)
            entry = WorkingMemoryEntry(
                memory_id=memory_id,
                layer=layer,
                scope_id=scope_id,
                logical_key=logical_key,
                content=content,
                knowledge_class=knowledge_class,
                provenance=request.provenance,
                created_at=now,
                expires_at=expires_at,
            )
            self._working[memory_id] = entry
            self._enforce_working_bound()
            return {
                "ok": True,
                "stored": True,
                "persistent": False,
                "memory_id": memory_id,
                "layer": layer.value,
                "scope_id": scope_id,
                "conflict": False,
                "conflicting_memory_ids": [],
            }

        try:
            existing = self._existing_versions(scope_id, layer, logical_key, now)
        except Exception:
            return {
                "ok": False,
                "error": "existing memory versions could not be verified",
                "stored": False,
            }

        conflicts = sorted(
            str(item.get("id"))
            for item in existing
            if self._clean(str(item.get("content") or "")) != content and item.get("id")
        )
        physical_key = f"v10:{layer.value}:{logical_key}:{content_hash[:16]}"
        metadata = {
            "v10_memory_schema": 1,
            "v10_layer": layer.value,
            "v10_logical_key": logical_key,
            "v10_content_hash": content_hash,
            "v10_knowledge_class": knowledge_class.value,
            "v10_provenance": request.provenance.to_dict(),
            "v10_created_at": now,
            "v10_expires_at": expires_at,
            "v10_persistent": True,
            "v10_conflict_at_write": bool(conflicts),
            "v10_conflicting_memory_ids": conflicts,
        }
        result = await self.memory_service.remember(
            physical_key,
            content,
            scope=scope,
            source=f"v10:{self._clean(request.provenance.source_type)}:{self._clean(request.provenance.source_id)}",
            metadata=metadata,
            **self._scope_kwargs(request.context),
        )
        if not result.get("ok"):
            return {
                "ok": False,
                "error": result.get("error") or "persistent memory write failed",
                "stored": False,
            }
        stored_memory = dict(result.get("memory") or {})
        return {
            "ok": True,
            "stored": True,
            "persistent": True,
            "memory_id": stored_memory.get("memory_id") or memory_id,
            "layer": layer.value,
            "scope_id": scope_id,
            "conflict": bool(conflicts),
            "conflicting_memory_ids": conflicts,
            "storage_key": result.get("storage_key"),
            "dimensions": result.get("dimensions", 0),
        }

    @classmethod
    def _tokens(cls, value: str) -> set[str]:
        return {match.group(0).lower() for match in cls._TOKEN_RE.finditer(value or "")}

    @classmethod
    def _working_score(cls, query: str, content: str, provenance: MemoryProvenance) -> float:
        query_tokens = cls._tokens(query)
        if not query_tokens:
            return 0.0
        overlap = len(query_tokens.intersection(cls._tokens(content))) / len(query_tokens)
        return min(1.0, 0.65 * overlap + 0.2 * provenance.confidence + 0.15 * provenance.authority)

    @staticmethod
    def _persistent_score(item: dict[str, Any], now: float) -> float:
        metadata = dict(item.get("metadata") or {})
        provenance = dict(metadata.get("v10_provenance") or {})
        semantic_score = max(0.0, min(float(item.get("score") or 0.0), 1.0))
        confidence = max(0.0, min(float(provenance.get("confidence") or 0.0), 1.0))
        authority = max(0.0, min(float(provenance.get("authority") or 0.0), 1.0))
        created_at = metadata.get("v10_created_at")
        if isinstance(created_at, (int, float)):
            age = max(0.0, now - float(created_at))
            freshness = max(0.0, 1.0 - min(age / (365.0 * 24.0 * 60.0 * 60.0), 1.0))
        else:
            freshness = 0.0
        return min(1.0, 0.55 * semantic_score + 0.2 * confidence + 0.15 * authority + 0.1 * freshness)

    @staticmethod
    def _normalize_layers(layers: Iterable[MemoryLayer | str] | None) -> list[MemoryLayer]:
        if layers is None:
            return list(MemoryLayer)
        output: list[MemoryLayer] = []
        seen: set[MemoryLayer] = set()
        for layer in layers:
            normalized = MemoryLayer(layer)
            if normalized in seen:
                continue
            seen.add(normalized)
            output.append(normalized)
        if not output:
            raise ValueError("at least one memory layer is required")
        return output

    async def recall(
        self,
        query: str,
        *,
        context: MemoryContext = MemoryContext(),
        layers: Iterable[MemoryLayer | str] | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        query = self._clean(query)
        if not query:
            return {"ok": False, "error": "memory query is required", "results": []}
        try:
            normalized_layers = self._normalize_layers(layers)
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc), "results": []}
        bounded_limit = max(1, min(int(limit), self.MAX_RECALL_LIMIT))
        visible_namespaces = ScopedMemory.visible_namespaces(**self._scope_kwargs(context))
        visible_set = set(visible_namespaces)
        now = float(self.clock())
        self._purge_expired_working(now)

        candidates: list[dict[str, Any]] = []
        persistent_layers = [layer for layer in normalized_layers if layer in self.PERSISTENT_LAYERS]
        if persistent_layers:
            semantic_result = await self.memory_service.semantic.search_many(
                query,
                visible_namespaces,
                limit=min(self.MAX_RECALL_LIMIT, max(bounded_limit * 4, bounded_limit)),
            )
            if not semantic_result.get("ok"):
                return {
                    "ok": False,
                    "error": semantic_result.get("error") or "persistent memory recall failed",
                    "results": [],
                }
            allowed_layers = {layer.value for layer in persistent_layers}
            for item in semantic_result.get("results", []):
                metadata = dict(item.get("metadata") or {})
                if metadata.get("v10_memory_schema") != 1:
                    continue
                if metadata.get("v10_layer") not in allowed_layers:
                    continue
                if item.get("namespace") not in visible_set:
                    continue
                expires_at = metadata.get("v10_expires_at")
                if isinstance(expires_at, (int, float)) and expires_at <= now:
                    continue
                candidate = dict(item)
                candidate["score"] = round(self._persistent_score(candidate, now), 6)
                candidates.append(candidate)

        if MemoryLayer.WORKING in normalized_layers:
            for entry in self._working.values():
                if entry.scope_id not in visible_set:
                    continue
                candidates.append(entry.to_result(self._working_score(query, entry.content, entry.provenance)))

        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for item in candidates:
            metadata = dict(item.get("metadata") or {})
            layer = str(metadata.get("v10_layer") or "")
            logical_key = str(metadata.get("v10_logical_key") or "")
            if not layer or not logical_key:
                continue
            group_key = (str(item.get("namespace") or ""), layer, logical_key)
            groups.setdefault(group_key, []).append(item)

        conflict_groups: list[dict[str, Any]] = []
        conflict_ids: set[str] = set()
        for (namespace, layer, logical_key), items in sorted(groups.items()):
            distinct_contents = {self._clean(str(item.get("content") or "")) for item in items}
            if len(distinct_contents) <= 1:
                continue
            ids = sorted(str(item.get("id")) for item in items if item.get("id"))
            conflict_ids.update(ids)
            conflict_groups.append(
                {
                    "namespace": namespace,
                    "layer": layer,
                    "logical_key": logical_key,
                    "memory_ids": ids,
                }
            )

        for item in candidates:
            item["conflict"] = str(item.get("id")) in conflict_ids
        candidates.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("namespace") or ""), str(item.get("id") or "")))
        return {
            "ok": True,
            "query": query,
            "namespaces": visible_namespaces,
            "layers": [layer.value for layer in normalized_layers],
            "results": candidates[:bounded_limit],
            "conflict_groups": conflict_groups,
            "has_conflicts": bool(conflict_groups),
        }

    def working_snapshot(self, *, context: MemoryContext = MemoryContext()) -> dict[str, Any]:
        now = float(self.clock())
        self._purge_expired_working(now)
        visible = set(ScopedMemory.visible_namespaces(**self._scope_kwargs(context)))
        items = [
            asdict(entry)
            for entry in sorted(self._working.values(), key=lambda item: (item.created_at, item.memory_id))
            if entry.scope_id in visible
        ]
        for item in items:
            item["layer"] = item["layer"].value if isinstance(item["layer"], MemoryLayer) else item["layer"]
            item["knowledge_class"] = (
                item["knowledge_class"].value
                if isinstance(item["knowledge_class"], KnowledgeClass)
                else item["knowledge_class"]
            )
        return {"ok": True, "items": items, "count": len(items)}
