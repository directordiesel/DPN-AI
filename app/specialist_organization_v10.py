from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


class SpecialistOrganizationError(ValueError):
    """Raised when specialist organization state or an assignment cannot be trusted."""


_ALLOWED_ASSIGNMENT_STATES = {"pending", "active", "handed_off", "completed", "cancelled"}
_TERMINAL_ASSIGNMENT_STATES = {"completed", "cancelled"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any, *, field_name: str, maximum: int, required: bool = True) -> str:
    text = " ".join(str(value or "").strip().split())
    if required and not text:
        raise SpecialistOrganizationError(f"{field_name} is required")
    if len(text) > maximum:
        raise SpecialistOrganizationError(f"{field_name} exceeds {maximum} characters")
    return text


def _clean_names(values: Iterable[str], *, field_name: str, maximum: int) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = _clean_text(raw, field_name=field_name, maximum=120)
        key = item.casefold()
        if key not in seen:
            result.append(item)
            seen.add(key)
    if len(result) > maximum:
        raise SpecialistOrganizationError(f"{field_name} exceeds {maximum} entries")
    return tuple(result)


def _digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SpecialistProfile:
    specialist_id: str
    name: str
    role: str
    description: str
    capability_tags: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    enabled: bool = False
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "capability_tags": list(self.capability_tags), "allowed_tools": list(self.allowed_tools)}


@dataclass(frozen=True)
class SpecialistAssignment:
    assignment_id: str
    specialist_id: str
    objective: str
    mission_id: str = ""
    required_tools: tuple[str, ...] = ()
    status: str = "pending"
    handoff_count: int = 0
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "required_tools": list(self.required_tools)}


@dataclass(frozen=True)
class HandoffReceipt:
    handoff_id: str
    assignment_id: str
    from_specialist_id: str
    to_specialist_id: str
    reason: str
    context_digest: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SpecialistOrganization:
    """Persistent organizational control plane for specialist identities and mission assignments.

    This layer never invokes a model or tool. It validates specialist capability boundaries,
    binds assignments to existing missions when requested, and records non-destructive handoff
    lineage. Execution remains the responsibility of existing agent/mission/ToolRegistry layers.
    """

    SCHEMA_VERSION = 1
    MAX_SPECIALISTS = 128
    MAX_ASSIGNMENTS = 2048
    MAX_HANDOFFS_PER_ASSIGNMENT = 16

    def __init__(
        self,
        path: str | Path,
        *,
        tool_catalog: Callable[[], list[dict[str, Any]]],
        mission_lookup: Callable[[str], dict[str, Any] | None] | None = None,
    ) -> None:
        self.path = Path(path)
        self._tool_catalog = tool_catalog
        self._mission_lookup = mission_lookup
        self._load_state()

    def _empty_state(self) -> dict[str, Any]:
        return {"schema_version": self.SCHEMA_VERSION, "specialists": [], "assignments": [], "handoffs": []}

    def _load_state(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty_state()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SpecialistOrganizationError("specialist organization state is unreadable") from exc
        self._validate_state(payload)
        return payload

    def _validate_state(self, payload: Any) -> None:
        if not isinstance(payload, dict) or payload.get("schema_version") != self.SCHEMA_VERSION:
            raise SpecialistOrganizationError("unsupported specialist organization state schema")
        specialists = payload.get("specialists")
        assignments = payload.get("assignments")
        handoffs = payload.get("handoffs")
        if not isinstance(specialists, list) or not isinstance(assignments, list) or not isinstance(handoffs, list):
            raise SpecialistOrganizationError("specialist organization state collections are invalid")
        if len(specialists) > self.MAX_SPECIALISTS or len(assignments) > self.MAX_ASSIGNMENTS:
            raise SpecialistOrganizationError("specialist organization state exceeds configured bounds")
        specialist_ids = [str(item.get("specialist_id") or "") for item in specialists if isinstance(item, dict)]
        assignment_ids = [str(item.get("assignment_id") or "") for item in assignments if isinstance(item, dict)]
        handoff_ids = [str(item.get("handoff_id") or "") for item in handoffs if isinstance(item, dict)]
        if len(specialist_ids) != len(specialists) or len(set(specialist_ids)) != len(specialist_ids) or "" in specialist_ids:
            raise SpecialistOrganizationError("specialist state contains invalid or duplicate specialist ids")
        if len(assignment_ids) != len(assignments) or len(set(assignment_ids)) != len(assignment_ids) or "" in assignment_ids:
            raise SpecialistOrganizationError("specialist state contains invalid or duplicate assignment ids")
        if len(handoff_ids) != len(handoffs) or len(set(handoff_ids)) != len(handoff_ids) or "" in handoff_ids:
            raise SpecialistOrganizationError("specialist state contains invalid or duplicate handoff ids")
        known_specialists = set(specialist_ids)
        known_assignments = set(assignment_ids)
        for item in assignments:
            if str(item.get("specialist_id") or "") not in known_specialists:
                raise SpecialistOrganizationError("assignment references an unknown specialist")
            if str(item.get("status") or "") not in _ALLOWED_ASSIGNMENT_STATES:
                raise SpecialistOrganizationError("assignment contains invalid lifecycle state")
            count = int(item.get("handoff_count", 0))
            if count < 0 or count > self.MAX_HANDOFFS_PER_ASSIGNMENT:
                raise SpecialistOrganizationError("assignment handoff count is invalid")
        for item in handoffs:
            if str(item.get("assignment_id") or "") not in known_assignments:
                raise SpecialistOrganizationError("handoff references an unknown assignment")
            if str(item.get("from_specialist_id") or "") not in known_specialists or str(item.get("to_specialist_id") or "") not in known_specialists:
                raise SpecialistOrganizationError("handoff references an unknown specialist")

    def _save(self, payload: dict[str, Any]) -> None:
        self._validate_state(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, sort_keys=True, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def _catalog_map(self) -> dict[str, dict[str, Any]]:
        catalog = self._tool_catalog()
        if not isinstance(catalog, list):
            raise SpecialistOrganizationError("tool catalog is unavailable")
        result: dict[str, dict[str, Any]] = {}
        for item in catalog:
            if isinstance(item, dict) and str(item.get("name") or "").strip():
                result[str(item["name"])] = item
        return result

    @staticmethod
    def _profile(raw: dict[str, Any]) -> SpecialistProfile:
        return SpecialistProfile(
            specialist_id=str(raw["specialist_id"]), name=str(raw["name"]), role=str(raw["role"]),
            description=str(raw.get("description") or ""), capability_tags=tuple(raw.get("capability_tags") or []),
            allowed_tools=tuple(raw.get("allowed_tools") or []), enabled=bool(raw.get("enabled", False)),
            created_at=str(raw.get("created_at") or ""), updated_at=str(raw.get("updated_at") or ""),
        )

    @staticmethod
    def _assignment(raw: dict[str, Any]) -> SpecialistAssignment:
        return SpecialistAssignment(
            assignment_id=str(raw["assignment_id"]), specialist_id=str(raw["specialist_id"]), objective=str(raw["objective"]),
            mission_id=str(raw.get("mission_id") or ""), required_tools=tuple(raw.get("required_tools") or []),
            status=str(raw.get("status") or "pending"), handoff_count=int(raw.get("handoff_count", 0)),
            created_at=str(raw.get("created_at") or ""), updated_at=str(raw.get("updated_at") or ""),
        )

    def list_specialists(self) -> list[SpecialistProfile]:
        state = self._load_state()
        return [self._profile(item) for item in state["specialists"]]

    def list_assignments(self, *, mission_id: str | None = None) -> list[SpecialistAssignment]:
        state = self._load_state()
        items = [self._assignment(item) for item in state["assignments"]]
        if mission_id is not None:
            key = _clean_text(mission_id, field_name="mission_id", maximum=160)
            items = [item for item in items if item.mission_id == key]
        return items

    def register_specialist(
        self, *, specialist_id: str, name: str, role: str, description: str = "",
        capability_tags: Iterable[str] = (), allowed_tools: Iterable[str] = (),
    ) -> SpecialistProfile:
        state = self._load_state()
        if len(state["specialists"]) >= self.MAX_SPECIALISTS:
            raise SpecialistOrganizationError("specialist capacity is exhausted")
        sid = _clean_text(specialist_id, field_name="specialist_id", maximum=80)
        if any(str(item["specialist_id"]).casefold() == sid.casefold() for item in state["specialists"]):
            raise SpecialistOrganizationError("specialist id already exists")
        tools = _clean_names(allowed_tools, field_name="allowed_tools", maximum=64)
        catalog = self._catalog_map()
        unknown = sorted(set(tools).difference(catalog))
        if unknown:
            raise SpecialistOrganizationError("specialist references unknown tools: " + ", ".join(unknown))
        now = _utc_now()
        profile = SpecialistProfile(
            specialist_id=sid,
            name=_clean_text(name, field_name="name", maximum=120),
            role=_clean_text(role, field_name="role", maximum=120),
            description=_clean_text(description, field_name="description", maximum=1000, required=False),
            capability_tags=_clean_names(capability_tags, field_name="capability_tags", maximum=32),
            allowed_tools=tools,
            enabled=False,
            created_at=now,
            updated_at=now,
        )
        state["specialists"].append(profile.to_dict())
        self._save(state)
        return profile

    def set_specialist_enabled(self, specialist_id: str, enabled: bool) -> SpecialistProfile:
        state = self._load_state()
        sid = _clean_text(specialist_id, field_name="specialist_id", maximum=80)
        for index, raw in enumerate(state["specialists"]):
            if str(raw["specialist_id"]).casefold() == sid.casefold():
                updated = {**raw, "enabled": bool(enabled), "updated_at": _utc_now()}
                state["specialists"][index] = updated
                self._save(state)
                return self._profile(updated)
        raise SpecialistOrganizationError("unknown specialist")

    def assign(
        self, *, assignment_id: str, specialist_id: str, objective: str,
        mission_id: str = "", required_tools: Iterable[str] = (),
    ) -> SpecialistAssignment:
        state = self._load_state()
        if len(state["assignments"]) >= self.MAX_ASSIGNMENTS:
            raise SpecialistOrganizationError("assignment capacity is exhausted")
        aid = _clean_text(assignment_id, field_name="assignment_id", maximum=100)
        if any(str(item["assignment_id"]).casefold() == aid.casefold() for item in state["assignments"]):
            raise SpecialistOrganizationError("assignment id already exists")
        specialist = self._find_enabled_specialist(state, specialist_id)
        required = _clean_names(required_tools, field_name="required_tools", maximum=64)
        self._validate_tool_coverage(specialist, required)
        mid = _clean_text(mission_id, field_name="mission_id", maximum=160, required=False)
        if mid:
            if self._mission_lookup is None:
                raise SpecialistOrganizationError("mission lookup is unavailable")
            if self._mission_lookup(mid) is None:
                raise SpecialistOrganizationError("assignment references an unknown mission")
        now = _utc_now()
        assignment = SpecialistAssignment(
            assignment_id=aid,
            specialist_id=specialist.specialist_id,
            objective=_clean_text(objective, field_name="objective", maximum=4000),
            mission_id=mid,
            required_tools=required,
            status="active",
            handoff_count=0,
            created_at=now,
            updated_at=now,
        )
        state["assignments"].append(assignment.to_dict())
        self._save(state)
        return assignment

    def handoff(
        self, *, assignment_id: str, to_specialist_id: str, reason: str, context: Any = None,
    ) -> tuple[SpecialistAssignment, HandoffReceipt]:
        state = self._load_state()
        aid = _clean_text(assignment_id, field_name="assignment_id", maximum=100)
        assignment_index = next((i for i, item in enumerate(state["assignments"]) if str(item["assignment_id"]).casefold() == aid.casefold()), None)
        if assignment_index is None:
            raise SpecialistOrganizationError("unknown assignment")
        current = self._assignment(state["assignments"][assignment_index])
        if current.status in _TERMINAL_ASSIGNMENT_STATES:
            raise SpecialistOrganizationError("terminal assignment cannot be handed off")
        if current.handoff_count >= self.MAX_HANDOFFS_PER_ASSIGNMENT:
            raise SpecialistOrganizationError("assignment handoff bound is exhausted")
        target = self._find_enabled_specialist(state, to_specialist_id)
        if target.specialist_id.casefold() == current.specialist_id.casefold():
            raise SpecialistOrganizationError("assignment cannot be handed off to the same specialist")
        self._validate_tool_coverage(target, current.required_tools)
        clean_reason = _clean_text(reason, field_name="reason", maximum=1000)
        context_digest = _digest(context if context is not None else {})
        handoff_id = _digest({"assignment_id": current.assignment_id, "from": current.specialist_id, "to": target.specialist_id, "count": current.handoff_count + 1, "context": context_digest})[:32]
        if any(str(item["handoff_id"]) == handoff_id for item in state["handoffs"]):
            raise SpecialistOrganizationError("duplicate specialist handoff detected")
        now = _utc_now()
        receipt = HandoffReceipt(handoff_id, current.assignment_id, current.specialist_id, target.specialist_id, clean_reason, context_digest, now)
        updated = SpecialistAssignment(
            assignment_id=current.assignment_id, specialist_id=target.specialist_id, objective=current.objective,
            mission_id=current.mission_id, required_tools=current.required_tools, status="active",
            handoff_count=current.handoff_count + 1, created_at=current.created_at, updated_at=now,
        )
        state["assignments"][assignment_index] = updated.to_dict()
        state["handoffs"].append(receipt.to_dict())
        self._save(state)
        return updated, receipt

    def set_assignment_status(self, assignment_id: str, status: str) -> SpecialistAssignment:
        state = self._load_state()
        aid = _clean_text(assignment_id, field_name="assignment_id", maximum=100)
        next_status = _clean_text(status, field_name="status", maximum=32).lower()
        if next_status not in _ALLOWED_ASSIGNMENT_STATES:
            raise SpecialistOrganizationError("invalid assignment lifecycle state")
        for index, raw in enumerate(state["assignments"]):
            if str(raw["assignment_id"]).casefold() == aid.casefold():
                current = self._assignment(raw)
                if current.status in _TERMINAL_ASSIGNMENT_STATES and next_status != current.status:
                    raise SpecialistOrganizationError("terminal assignment state cannot be reopened")
                updated = {**raw, "status": next_status, "updated_at": _utc_now()}
                state["assignments"][index] = updated
                self._save(state)
                return self._assignment(updated)
        raise SpecialistOrganizationError("unknown assignment")

    def assignment_context(self, assignment_id: str) -> dict[str, Any]:
        state = self._load_state()
        assignment = next((self._assignment(item) for item in state["assignments"] if str(item["assignment_id"]) == assignment_id), None)
        if assignment is None:
            raise SpecialistOrganizationError("unknown assignment")
        specialist = next((self._profile(item) for item in state["specialists"] if str(item["specialist_id"]) == assignment.specialist_id), None)
        if specialist is None or not specialist.enabled:
            raise SpecialistOrganizationError("assignment specialist is unavailable")
        catalog = self._catalog_map()
        allowed = [catalog[name] for name in specialist.allowed_tools if name in catalog]
        if len(allowed) != len(specialist.allowed_tools):
            raise SpecialistOrganizationError("specialist tool boundary drift detected")
        return {
            "assignment": assignment.to_dict(),
            "specialist": specialist.to_dict(),
            "allowed_tool_catalog": allowed,
            "execution_authorized": False,
            "mission_bound": bool(assignment.mission_id),
        }

    def _find_enabled_specialist(self, state: dict[str, Any], specialist_id: str) -> SpecialistProfile:
        sid = _clean_text(specialist_id, field_name="specialist_id", maximum=80)
        for raw in state["specialists"]:
            if str(raw["specialist_id"]).casefold() == sid.casefold():
                profile = self._profile(raw)
                if not profile.enabled:
                    raise SpecialistOrganizationError("specialist is disabled")
                return profile
        raise SpecialistOrganizationError("unknown specialist")

    def _validate_tool_coverage(self, specialist: SpecialistProfile, required_tools: Iterable[str]) -> None:
        required = set(required_tools)
        catalog = self._catalog_map()
        if not required.issubset(catalog):
            raise SpecialistOrganizationError("assignment requires unknown tools")
        if not required.issubset(set(specialist.allowed_tools)):
            raise SpecialistOrganizationError("specialist capability boundary does not cover required tools")

    def status(self) -> dict[str, Any]:
        state = self._load_state()
        enabled = sum(1 for item in state["specialists"] if bool(item.get("enabled", False)))
        active = sum(1 for item in state["assignments"] if str(item.get("status")) not in _TERMINAL_ASSIGNMENT_STATES)
        return {
            "ok": True,
            "schema_version": self.SCHEMA_VERSION,
            "specialists": len(state["specialists"]),
            "enabled_specialists": enabled,
            "assignments": len(state["assignments"]),
            "active_assignments": active,
            "handoffs": len(state["handoffs"]),
            "execution_authorized": False,
        }


__all__ = ["HandoffReceipt", "SpecialistAssignment", "SpecialistOrganization", "SpecialistOrganizationError", "SpecialistProfile"]
