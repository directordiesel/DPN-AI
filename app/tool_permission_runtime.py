from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.permission_engine import PermissionDecision, PermissionEngine, PermissionMode, RiskLevel
from app.tool_risk import ToolRiskClassifier, ToolRiskProfile


LEGACY_GATE_MAP = {
    "commands": "allow_commands",
    "web": "allow_web",
    "images": "allow_images",
    "browser": "allow_browser",
    "desktop": "allow_desktop",
    "voice": "allow_voice",
    "connectors": "allow_connectors",
    "mcp": "allow_mcp",
    "self_improvement": "allow_self_improvement",
}


@dataclass(frozen=True)
class ToolAuthorization:
    allowed: bool
    approval_required: bool
    reason: str
    decision: PermissionDecision
    profile: ToolRiskProfile

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "approval_required": self.approval_required,
            "reason": self.reason,
            "decision": self.decision.to_dict(),
            "profile": self.profile.to_dict(),
        }


class ToolPermissionRuntime:
    """Compatibility bridge between legacy gates and v9 permission policies.

    Legacy feature gates remain a hard prerequisite. A disabled feature can never
    be re-enabled by a v9 permission rule. When no explicit v9 rule is supplied,
    read/write tools preserve current behavior while side-effectful tools preserve
    the existing approval-mode behavior. Explicit v9 rules then take precedence
    within that already-authorized feature boundary.
    """

    def __init__(self, engine: PermissionEngine | None = None):
        self.engine = engine or PermissionEngine(PermissionMode.ALWAYS_ALLOW)

    @staticmethod
    def _legacy_gate_allowed(gate: str | None, permissions: dict[str, Any]) -> tuple[bool, str]:
        if not gate:
            return True, ""
        key = LEGACY_GATE_MAP.get(gate)
        if not key:
            return False, f"Unknown permission gate '{gate}'"
        if not bool(permissions.get(key, False)):
            return False, f"Permission gate '{gate}' is disabled"
        return True, ""

    @staticmethod
    def _legacy_mode_decision(profile: ToolRiskProfile, permissions: dict[str, Any]) -> PermissionDecision:
        mode = str(permissions.get("approval_mode", "standard") or "standard").lower()
        risk = profile.risk
        if mode == "safe" and risk in {RiskLevel.EXECUTE, RiskLevel.EXTERNAL, RiskLevel.DESTRUCTIVE, RiskLevel.DESKTOP}:
            return PermissionDecision(False, False, PermissionMode.DENY, "legacy Safe mode blocks this risk", "legacy", risk)
        if mode == "standard" and risk in {RiskLevel.EXTERNAL, RiskLevel.DESTRUCTIVE, RiskLevel.DESKTOP}:
            return PermissionDecision(False, True, PermissionMode.ASK_EVERY_TIME, "legacy Standard mode requires approval", "legacy", risk)
        return PermissionDecision(True, False, PermissionMode.ALWAYS_ALLOW, "legacy mode permits execution", "legacy", risk)

    def authorize(
        self,
        *,
        tool_name: str,
        declared_risk: str,
        gate: str | None,
        permissions: dict[str, Any],
        use_v9_policy: bool = False,
    ) -> ToolAuthorization:
        profile = ToolRiskClassifier.classify(tool_name, declared_risk)
        gate_allowed, gate_reason = self._legacy_gate_allowed(gate, permissions)
        if not gate_allowed:
            decision = PermissionDecision(False, False, PermissionMode.DENY, gate_reason, "legacy_gate", profile.risk)
            return ToolAuthorization(False, False, gate_reason, decision, profile)

        if use_v9_policy:
            decision = self.engine.evaluate(tool_name, profile.risk, gate)
        else:
            decision = self._legacy_mode_decision(profile, permissions)

        return ToolAuthorization(
            allowed=decision.allowed,
            approval_required=decision.approval_required,
            reason=decision.reason,
            decision=decision,
            profile=profile,
        )
