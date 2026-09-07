from __future__ import annotations

from app.memory_tool_service_v10 import GovernedMemoryToolService


SCOPE_PROPERTIES = {
    "organization_id": {"type": "string", "default": ""},
    "user_id": {"type": "string", "default": ""},
    "project_id": {"type": "string", "default": ""},
    "conversation_id": {"type": "string", "default": ""},
}


def register(registry) -> None:
    # A host may inject a callable memory_scope_authorizer(scope, MemoryContext).
    # Without it, the service deliberately permits only global memory access.
    service = GovernedMemoryToolService(
        registry.db,
        registry.semantic,
        scope_authorizer=getattr(registry, "memory_scope_authorizer", None),
    )
    registry.register(
        name="dpn_memory_recall",
        description="Recall v10 layered memory through privacy-scoped namespaces with provenance/conflict-aware ranking. Non-global identifiers require host authorization; raw storage access is not exposed.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "layers": {"type": ["array", "null"], "items": {"type": "string"}, "default": None, "maxItems": 8},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 8},
                **SCOPE_PROPERTIES,
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        function=service.recall,
        risk="read",
    )
    registry.register(
        name="dpn_memory_remember",
        description="Store one bounded non-sensitive v10 memory through typed provenance, scope isolation, evidence requirements, conflict preservation and retention validation. Non-global scope identifiers require host authorization.",
        parameters={
            "type": "object",
            "properties": {
                "layer": {"type": "string", "enum": ["working", "conversation", "project", "organization", "user", "procedural", "episodic", "semantic"]},
                "key": {"type": "string"}, "content": {"type": "string"},
                "knowledge_class": {"type": "string", "enum": ["observation", "fact", "derived", "inference", "procedure", "episode"]},
                "source_type": {"type": "string"}, "source_id": {"type": "string"},
                "evidence_ids": {"type": ["array", "null"], "items": {"type": "string"}, "default": None, "maxItems": 128},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 1.0},
                "authority": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
                "scope": {"type": ["string", "null"], "enum": ["global", "organization", "user", "project", "conversation", None], "default": None},
                "ttl_seconds": {"type": ["integer", "null"], "minimum": 1, "default": None},
                **SCOPE_PROPERTIES,
            },
            "required": ["layer", "key", "content", "knowledge_class", "source_type", "source_id"],
            "additionalProperties": False,
        },
        function=service.remember,
        risk="execute",
    )
    registry.register(
        name="dpn_memory_lineage_inspect",
        description="Inspect the non-destructive compacted memory view for one exact host-authorized scope, including duplicates, preferred versions and recovery-required lineage findings.",
        parameters={
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["global", "organization", "user", "project", "conversation"]},
                **SCOPE_PROPERTIES,
            },
            "required": ["scope"],
            "additionalProperties": False,
        },
        function=service.inspect_lineage,
        risk="read",
    )
    registry.register(
        name="dpn_memory_supersede",
        description="Create an evidence-backed replacement plus immutable lineage receipt inside a host-authorized scope. Prior versions remain stored. This preference-changing action always requires explicit human approval.",
        parameters={
            "type": "object",
            "properties": {
                "layer": {"type": "string", "enum": ["conversation", "project", "organization", "user", "procedural", "episodic", "semantic"]},
                "key": {"type": "string"}, "content": {"type": "string"},
                "knowledge_class": {"type": "string", "enum": ["observation", "fact", "derived", "inference", "procedure", "episode"]},
                "source_type": {"type": "string"}, "source_id": {"type": "string"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 128},
                "supersedes_memory_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 32},
                "reason": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 1.0},
                "authority": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
                "scope": {"type": ["string", "null"], "enum": ["global", "organization", "user", "project", "conversation", None], "default": None},
                **SCOPE_PROPERTIES,
            },
            "required": ["layer", "key", "content", "knowledge_class", "source_type", "source_id", "evidence_ids", "supersedes_memory_ids", "reason"],
            "additionalProperties": False,
        },
        function=service.supersede,
        risk="destructive",
    )
