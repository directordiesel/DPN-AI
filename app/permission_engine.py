from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class PermissionMode(str, Enum):
    ASK_EVERY_TIME = "ask_every_time"
    ALLOW_SESSION = "allow_session"
    ALWAYS_ALLOW = "always_allow"
    DENY = "deny"


class RiskLevel(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    EXTERNAL = "external"
    DESTRUCTIVE = "destructive"
    DESKTOP = "desktop"


RISK_ORDER = {
    RiskLevel.READ: 0,
    RiskLevel.WRITE: 1,
    RiskLevel.EXECUTE: 2,
    RiskLevel.EXTERNAL: 3,
    RiskLevel.DESTRUCTIVE: 4,
    RiskLevel.DESKTOP: 4,
}

# These risks can directly destroy user data or operate the host desktop. They
# are intentionally never satisfied by session or persistent grants. A human
# must approve each invocation so a broad rule cannot silently become durable
# authority for the most consequential actions.
PER_INVOCATION_RISKS = frozenset({RiskLevel.DESTRUCTIVE, RiskLevel.DESKTOP})


@dataclass(frozen=True)
class PermissionRule:
    mode: PermissionMode
    max_risk: RiskLevel = RiskLevel.READ


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    approval_required: bool
    mode: PermissionMode
    reason: str
    source: str
    risk: RiskLevel

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PermissionEngine:
    """Deterministic, fail-closed permission evaluation for DPN AI tools.

    Rule precedence is explicit tool > capability gate > default. Session grants
    never become persistent grants. Risk above the rule ceiling escalates to a
    human approval rather than silently expanding authority. Destructive and
    desktop-control actions always require fresh per-invocation approval, even if
    a session or persistent rule would otherwise allow them.
    """

    def __init__(self, default_mode: PermissionMode = PermissionMode.ASK_EVERY_TIME):
        self.default_mode = PermissionMode(default_mode)
        self._tool_rules: dict[str, PermissionRule] = {}
        self._gate_rules: dict[str, PermissionRule] = {}
        self._session_grants: set[str] = set()

    @staticmethod
    def normalize_risk(value: str | RiskLevel) -> RiskLevel:
        if isinstance(value, RiskLevel):
            return value
        try:
            return RiskLevel(str(value))
        except ValueError as exc:
            raise ValueError(f"unsupported risk level: {value}") from exc

    def set_tool_rule(self, tool_name: str, mode: PermissionMode, max_risk: RiskLevel = RiskLevel.READ) -> None:
        name = (tool_name or "").strip()
        if not name:
            raise ValueError("tool_name is required")
        self._tool_rules[name] = PermissionRule(PermissionMode(mode), self.normalize_risk(max_risk))

    def set_gate_rule(self, gate: str, mode: PermissionMode, max_risk: RiskLevel = RiskLevel.READ) -> None:
        name = (gate or "").strip()
        if not name:
            raise ValueError("gate is required")
        self._gate_rules[name] = PermissionRule(PermissionMode(mode), self.normalize_risk(max_risk))

    def grant_session(self, tool_name: str) -> None:
        name = (tool_name or "").strip()
        if not name:
            raise ValueError("tool_name is required")
        self._session_grants.add(name)

    def revoke_session(self, tool_name: str) -> None:
        self._session_grants.discard((tool_name or "").strip())

    def clear_session(self) -> None:
        self._session_grants.clear()

    def _rule_for(self, tool_name: str, gate: str | None) -> tuple[PermissionRule, str]:
        if tool_name in self._tool_rules:
            return self._tool_rules[tool_name], "tool"
        if gate and gate in self._gate_rules:
            return self._gate_rules[gate], "gate"
        return PermissionRule(self.default_mode, RiskLevel.READ), "default"

    def evaluate(self, tool_name: str, risk: str | RiskLevel, gate: str | None = None) -> PermissionDecision:
        name = (tool_name or "").strip()
        if not name:
            raise ValueError("tool_name is required")
        normalized_risk = self.normalize_risk(risk)
        rule, source = self._rule_for(name, gate)

        if rule.mode == PermissionMode.DENY:
            return PermissionDecision(False, False, rule.mode, "permission rule denies this tool", source, normalized_risk)

        if RISK_ORDER[normalized_risk] > RISK_ORDER[rule.max_risk]:
            return PermissionDecision(
                False,
                True,
                rule.mode,
                f"tool risk {normalized_risk.value} exceeds allowed ceiling {rule.max_risk.value}",
                source,
                normalized_risk,
            )

        if normalized_risk in PER_INVOCATION_RISKS:
            return PermissionDecision(
                False,
                True,
                PermissionMode.ASK_EVERY_TIME,
                f"{normalized_risk.value} actions require fresh human approval for every invocation",
                "high_risk_floor",
                normalized_risk,
            )

        if rule.mode == PermissionMode.ASK_EVERY_TIME:
            return PermissionDecision(False, True, rule.mode, "human approval required for every invocation", source, normalized_risk)

        if rule.mode == PermissionMode.ALLOW_SESSION:
            if name in self._session_grants:
                return PermissionDecision(True, False, rule.mode, "tool is allowed for the current session", source, normalized_risk)
            return PermissionDecision(False, True, rule.mode, "session approval has not been granted", source, normalized_risk)

        if rule.mode == PermissionMode.ALWAYS_ALLOW:
            return PermissionDecision(True, False, rule.mode, "persistent permission rule allows this tool", source, normalized_risk)

        return PermissionDecision(False, True, PermissionMode.ASK_EVERY_TIME, "unknown permission state; fail closed", source, normalized_risk)

    def snapshot(self) -> dict[str, Any]:
        return {
            "default_mode": self.default_mode.value,
            "tool_rules": {name: {"mode": rule.mode.value, "max_risk": rule.max_risk.value} for name, rule in sorted(self._tool_rules.items())},
            "gate_rules": {name: {"mode": rule.mode.value, "max_risk": rule.max_risk.value} for name, rule in sorted(self._gate_rules.items())},
            "session_grants": sorted(self._session_grants),
        }
