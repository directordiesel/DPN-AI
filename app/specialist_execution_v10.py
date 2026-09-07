from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping


class SpecialistExecutionError(ValueError):
    """Raised when specialist-scoped execution cannot be trusted."""


@dataclass(frozen=True)
class SpecialistExecutionReceipt:
    assignment_id: str
    specialist_id: str
    tool_name: str
    mission_id: str
    ok: bool
    approval_pending: bool
    execution_authorized_by_specialist: bool
    result: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "assignment_id": self.assignment_id,
            "specialist_id": self.specialist_id,
            "tool_name": self.tool_name,
            "mission_id": self.mission_id,
            "ok": self.ok,
            "approval_pending": self.approval_pending,
            "execution_authorized_by_specialist": self.execution_authorized_by_specialist,
            "result": dict(self.result),
        }


class SpecialistExecutionFacade:
    """Capability-scoped bridge into the existing ToolRegistry execution authority.

    This facade does not grant permission. It validates a live specialist assignment,
    restricts the requested tool to the assignment specialist's current allowlist,
    then delegates to the existing ToolRegistry.execute path. ApprovalSecurity remains
    authoritative for external/execute/destructive operations.
    """

    def __init__(
        self,
        *,
        resolve_assignment: Callable[[str], Mapping[str, Any]],
        execute_tool: Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]],
        mission_lookup: Callable[[str], dict[str, Any] | None] | None = None,
    ) -> None:
        self._resolve_assignment = resolve_assignment
        self._execute_tool = execute_tool
        self._mission_lookup = mission_lookup

    @staticmethod
    def _clean_tool_name(value: Any) -> str:
        name = str(value or "").strip()
        if not name or len(name) > 120:
            raise SpecialistExecutionError("valid tool name is required")
        return name

    @staticmethod
    def _clean_arguments(arguments: Any) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise SpecialistExecutionError("tool arguments must be an object")
        return dict(arguments)

    @staticmethod
    def _allowed_names(context: Mapping[str, Any]) -> set[str]:
        catalog = context.get("allowed_tool_catalog")
        if not isinstance(catalog, list):
            raise SpecialistExecutionError("specialist assignment tool catalog is unavailable")
        names = {
            str(item.get("name") or "").strip()
            for item in catalog
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }
        if len(names) != len(catalog):
            raise SpecialistExecutionError("specialist assignment tool catalog is malformed")
        return names

    async def execute(
        self,
        *,
        assignment_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        permissions: dict[str, Any],
    ) -> SpecialistExecutionReceipt:
        aid = str(assignment_id or "").strip()
        if not aid or len(aid) > 100:
            raise SpecialistExecutionError("valid assignment id is required")
        if not isinstance(permissions, dict):
            raise SpecialistExecutionError("host-resolved permissions are required")

        context = self._resolve_assignment(aid)
        if not isinstance(context, Mapping):
            raise SpecialistExecutionError("specialist assignment context is unavailable")
        if context.get("execution_authorized") is not False:
            raise SpecialistExecutionError("specialist assignment context must remain non-authorizing")

        assignment = context.get("assignment")
        specialist = context.get("specialist")
        if not isinstance(assignment, Mapping) or not isinstance(specialist, Mapping):
            raise SpecialistExecutionError("specialist assignment context is malformed")
        if str(assignment.get("assignment_id") or "") != aid:
            raise SpecialistExecutionError("specialist assignment identity mismatch")
        if str(assignment.get("status") or "") != "active":
            raise SpecialistExecutionError("specialist assignment is not active")
        if not bool(specialist.get("enabled", False)):
            raise SpecialistExecutionError("specialist is disabled")

        requested_tool = self._clean_tool_name(tool_name)
        allowed_names = self._allowed_names(context)
        if requested_tool not in allowed_names:
            raise SpecialistExecutionError("tool is outside specialist capability boundary")

        required_tools = assignment.get("required_tools") or []
        if not isinstance(required_tools, list):
            raise SpecialistExecutionError("assignment required-tool boundary is malformed")
        if any(str(name) not in allowed_names for name in required_tools):
            raise SpecialistExecutionError("assignment capability boundary drift detected")

        mission_id = str(assignment.get("mission_id") or "").strip()
        if mission_id:
            if self._mission_lookup is None:
                raise SpecialistExecutionError("mission verification is unavailable")
            mission = self._mission_lookup(mission_id)
            if not isinstance(mission, dict):
                raise SpecialistExecutionError("bound mission no longer exists")
            mission_status = str(mission.get("status") or "").strip().lower()
            if mission_status in {"completed", "cancelled", "failed"}:
                raise SpecialistExecutionError("bound mission is terminal")

        result = await self._execute_tool(requested_tool, self._clean_arguments(arguments), dict(permissions))
        if not isinstance(result, dict):
            raise SpecialistExecutionError("tool registry returned malformed execution result")
        approval_pending = bool(result.get("approval_required") or result.get("approval_pending") or result.get("pending_approval"))
        return SpecialistExecutionReceipt(
            assignment_id=aid,
            specialist_id=str(specialist.get("specialist_id") or ""),
            tool_name=requested_tool,
            mission_id=mission_id,
            ok=bool(result.get("ok", False)),
            approval_pending=approval_pending,
            execution_authorized_by_specialist=False,
            result=result,
        )


__all__ = ["SpecialistExecutionError", "SpecialistExecutionFacade", "SpecialistExecutionReceipt"]
