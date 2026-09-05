from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.permission_engine import RiskLevel


@dataclass(frozen=True)
class ToolRiskProfile:
    risk: RiskLevel
    requires_sandbox: bool = False
    network_effect: bool = False
    host_effect: bool = False
    credential_effect: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk": self.risk.value,
            "requires_sandbox": self.requires_sandbox,
            "network_effect": self.network_effect,
            "host_effect": self.host_effect,
            "credential_effect": self.credential_effect,
        }


class ToolRiskClassifier:
    """Centralized conservative risk metadata for registered tool execution."""

    HIGH_RISK_NAMES = {
        "delete_path": ToolRiskProfile(RiskLevel.DESTRUCTIVE, host_effect=True),
        "desktop_automation": ToolRiskProfile(RiskLevel.DESKTOP, host_effect=True),
        "browser_automation": ToolRiskProfile(RiskLevel.EXTERNAL, network_effect=True, host_effect=True),
        "connector_request": ToolRiskProfile(RiskLevel.EXTERNAL, network_effect=True, credential_effect=True),
        "call_mcp_tool": ToolRiskProfile(RiskLevel.EXTERNAL, network_effect=True, credential_effect=True),
        "run_command": ToolRiskProfile(RiskLevel.EXECUTE, host_effect=True),
        "run_python_sandbox": ToolRiskProfile(RiskLevel.EXECUTE, requires_sandbox=True),
    }

    @classmethod
    def classify(cls, name: str, declared_risk: str) -> ToolRiskProfile:
        tool_name = (name or "").strip()
        if not tool_name:
            raise ValueError("tool name is required")
        explicit = cls.HIGH_RISK_NAMES.get(tool_name)
        if explicit:
            return explicit
        try:
            risk = RiskLevel(str(declared_risk))
        except ValueError as exc:
            raise ValueError(f"unsupported declared tool risk: {declared_risk}") from exc
        return ToolRiskProfile(risk)
