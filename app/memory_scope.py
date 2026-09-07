from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
from typing import Any


class MemoryScope(str, Enum):
    GLOBAL = "global"
    ORGANIZATION = "organization"
    USER = "user"
    PROJECT = "project"
    CONVERSATION = "conversation"


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    scope: MemoryScope
    scope_id: str
    key: str
    value: str
    source: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["scope"] = self.scope.value
        return value


class ScopedMemory:
    """Namespace and validation rules for durable memory.

    Storage remains delegated to the existing database/semantic layers. The
    namespace model is deliberately explicit so organization, user, project,
    and conversation memories are never made visible without the matching
    active scope identifier.
    """

    @staticmethod
    def scope_id(
        scope: MemoryScope | str,
        *,
        organization_id: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
    ) -> str:
        normalized = MemoryScope(scope)
        if normalized == MemoryScope.GLOBAL:
            return "global"
        if normalized == MemoryScope.ORGANIZATION:
            organization = (organization_id or "").strip()
            if not organization:
                raise ValueError("organization_id is required for organization memory")
            return f"organization:{organization}"
        if normalized == MemoryScope.USER:
            user = (user_id or "").strip()
            if not user:
                raise ValueError("user_id is required for user memory")
            return f"user:{user}"
        if normalized == MemoryScope.PROJECT:
            project = (project_id or "").strip()
            if not project:
                raise ValueError("project_id is required for project memory")
            return f"project:{project}"
        conversation = (conversation_id or "").strip()
        if not conversation:
            raise ValueError("conversation_id is required for conversation memory")
        return f"conversation:{conversation}"

    @staticmethod
    def build(
        key: str,
        value: str,
        *,
        scope: MemoryScope | str = MemoryScope.GLOBAL,
        organization_id: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        source: str = "manual",
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord:
        normalized_key = (key or "").strip()
        normalized_value = (value or "").strip()
        if not normalized_key:
            raise ValueError("memory key is required")
        if not normalized_value:
            raise ValueError("memory value is required")
        sid = ScopedMemory.scope_id(
            scope,
            organization_id=organization_id,
            user_id=user_id,
            project_id=project_id,
            conversation_id=conversation_id,
        )
        raw = f"{sid}\0{normalized_key.lower()}"
        memory_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
        return MemoryRecord(
            memory_id=memory_id,
            scope=MemoryScope(scope),
            scope_id=sid,
            key=normalized_key,
            value=normalized_value,
            source=(source or "manual").strip() or "manual",
            metadata=dict(metadata or {}),
        )

    @staticmethod
    def visible_namespaces(
        *,
        organization_id: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
    ) -> list[str]:
        namespaces = ["global"]
        if organization_id and organization_id.strip():
            namespaces.append(f"organization:{organization_id.strip()}")
        if user_id and user_id.strip():
            namespaces.append(f"user:{user_id.strip()}")
        if project_id and project_id.strip():
            namespaces.append(f"project:{project_id.strip()}")
        if conversation_id and conversation_id.strip():
            namespaces.append(f"conversation:{conversation_id.strip()}")
        return namespaces
