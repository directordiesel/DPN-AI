from __future__ import annotations

from typing import Any

from app.memory_tool_runtime_v10 import GovernedMemoryToolRuntime


_RUNTIME: GovernedMemoryToolRuntime | None = None


def configure_memory_tool_runtime(runtime: GovernedMemoryToolRuntime) -> None:
    global _RUNTIME
    _RUNTIME = runtime


def _runtime() -> GovernedMemoryToolRuntime:
    if _RUNTIME is None:
        raise RuntimeError("governed memory tool runtime is not configured")
    return _RUNTIME


async def dpn_memory_recall(query: str, layers: list[str] | None = None, limit: int = 8) -> dict[str, Any]:
    try:
        return await _runtime().recall(query, layers=layers, limit=limit)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"memory recall unavailable: {type(exc).__name__}", "results": []}


async def dpn_memory_remember(
    layer: str,
    key: str,
    content: str,
    knowledge_class: str,
    source_type: str,
    source_id: str,
    evidence_ids: list[str] | None = None,
    confidence: float = 1.0,
    authority: float = 0.5,
    scope: str | None = None,
    ttl_seconds: int | None = None,
    sensitive: bool = False,
) -> dict[str, Any]:
    try:
        return await _runtime().remember(
            layer=layer,
            key=key,
            content=content,
            knowledge_class=knowledge_class,
            source_type=source_type,
            source_id=source_id,
            evidence_ids=evidence_ids,
            confidence=confidence,
            authority=authority,
            scope=scope,
            ttl_seconds=ttl_seconds,
            sensitive=sensitive,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"memory write unavailable: {type(exc).__name__}", "stored": False}


def dpn_memory_inspect_lineage(scope: str) -> dict[str, Any]:
    try:
        return _runtime().inspect_lineage(scope=scope)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"memory lineage unavailable: {type(exc).__name__}", "report": None}


async def dpn_memory_supersede(
    layer: str,
    key: str,
    content: str,
    knowledge_class: str,
    source_type: str,
    source_id: str,
    evidence_ids: list[str],
    supersedes_memory_ids: list[str],
    reason: str,
    confidence: float = 1.0,
    authority: float = 0.5,
    scope: str | None = None,
    ttl_seconds: int | None = None,
    sensitive: bool = False,
) -> dict[str, Any]:
    try:
        return await _runtime().supersede(
            layer=layer,
            key=key,
            content=content,
            knowledge_class=knowledge_class,
            source_type=source_type,
            source_id=source_id,
            evidence_ids=evidence_ids,
            supersedes_memory_ids=supersedes_memory_ids,
            reason=reason,
            confidence=confidence,
            authority=authority,
            scope=scope,
            ttl_seconds=ttl_seconds,
            sensitive=sensitive,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"memory supersession unavailable: {type(exc).__name__}", "stored": False}


def register(registry) -> None:
    registry.register(
        name="dpn_memory_recall",
        description="Recall v10 layered memory visible to the host-injected trusted organization/user/project/conversation context. Tool arguments cannot supply tenant or identity scope IDs.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "layers": {"type": ["array", "null"], "items": {"type": "string", "enum": ["working", "conversation", "project", "organization", "user", "procedural", "episodic", "semantic"]}, "default": None},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 8}
            },
            "required": ["query"],
            "additionalProperties": False
        },
        function=dpn_memory_recall,
        risk="read",
    )
    registry.register(
        name="dpn_memory_remember",
        description="Write bounded v10 memory through AdvancedLayeredMemory using host-injected trusted scope context. Sensitive persistent writes still require the configured external approval guard.",
        parameters={
            "type": "object",
            "properties": {
                "layer": {"type": "string", "enum": ["working", "conversation", "project", "organization", "user", "procedural", "episodic", "semantic"]},
                "key": {"type": "string", "minLength": 1, "maxLength": 256},
                "content": {"type": "string", "minLength": 1, "maxLength": 20000},
                "knowledge_class": {"type": "string", "enum": ["observation", "fact", "derived", "inference", "procedure", "episode"]},
                "source_type": {"type": "string", "minLength": 1},
                "source_id": {"type": "string", "minLength": 1},
                "evidence_ids": {"type": ["array", "null"], "items": {"type": "string", "minLength": 1}, "maxItems": 128, "default": None},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 1.0},
                "authority": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
                "scope": {"type": ["string", "null"], "enum": ["global", "organization", "user", "project", "conversation", None], "default": None},
                "ttl_seconds": {"type": ["integer", "null"], "minimum": 1, "default": None},
                "sensitive": {"type": "boolean", "default": False}
            },
            "required": ["layer", "key", "content", "knowledge_class", "source_type", "source_id"],
            "additionalProperties": False
        },
        function=dpn_memory_remember,
        risk="write",
    )
    registry.register(
        name="dpn_memory_inspect_lineage",
        description="Inspect the non-destructive canonical/preferred memory view and lineage recovery findings for one scope available in the trusted host context.",
        parameters={
            "type": "object",
            "properties": {"scope": {"type": "string", "enum": ["global", "organization", "user", "project", "conversation"]}},
            "required": ["scope"],
            "additionalProperties": False
        },
        function=dpn_memory_inspect_lineage,
        risk="read",
    )
    registry.register(
        name="dpn_memory_supersede",
        description="Request evidence-backed non-destructive durable memory supersession. The tool is always human-approval gated by ToolPermissionRuntime and still preserves all historical versions.",
        parameters={
            "type": "object",
            "properties": {
                "layer": {"type": "string", "enum": ["conversation", "project", "organization", "user", "procedural", "episodic", "semantic"]},
                "key": {"type": "string", "minLength": 1, "maxLength": 256},
                "content": {"type": "string", "minLength": 1, "maxLength": 20000},
                "knowledge_class": {"type": "string", "enum": ["observation", "fact", "derived", "inference", "procedure", "episode"]},
                "source_type": {"type": "string", "minLength": 1},
                "source_id": {"type": "string", "minLength": 1},
                "evidence_ids": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1, "maxItems": 128},
                "supersedes_memory_ids": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1, "maxItems": 32},
                "reason": {"type": "string", "minLength": 1, "maxLength": 1000},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 1.0},
                "authority": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
                "scope": {"type": ["string", "null"], "enum": ["global", "organization", "user", "project", "conversation", None], "default": None},
                "ttl_seconds": {"type": ["integer", "null"], "minimum": 1, "default": None},
                "sensitive": {"type": "boolean", "default": False}
            },
            "required": ["layer", "key", "content", "knowledge_class", "source_type", "source_id", "evidence_ids", "supersedes_memory_ids", "reason"],
            "additionalProperties": False
        },
        function=dpn_memory_supersede,
        risk="write",
    )


__all__ = ["configure_memory_tool_runtime", "dpn_memory_inspect_lineage", "dpn_memory_recall", "dpn_memory_remember", "dpn_memory_supersede", "register"]
