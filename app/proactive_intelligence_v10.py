from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


_ALLOWED_OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte"}
_ALLOWED_TOOL_RISKS = {"read", "write", "execute", "external", "destructive"}
_MAX_ID = 120
_MAX_ARGS_JSON = 16_384


class ProactiveIntelligenceError(ValueError):
    """Raised when a proactive condition or observation is not safely evaluable."""


@dataclass(frozen=True)
class ConditionSpec:
    condition_id: str
    operator: str
    threshold: Any
    action_tool: str
    action_args: Mapping[str, Any]
    cooldown_seconds: int = 300
    edge_triggered: bool = True

    def validate(self) -> None:
        condition_id = self.condition_id.strip()
        if not condition_id or len(condition_id) > _MAX_ID:
            raise ProactiveIntelligenceError("condition_id must be 1-120 characters")
        if self.operator not in _ALLOWED_OPERATORS:
            raise ProactiveIntelligenceError("unsupported condition operator")
        if not self.action_tool.strip() or len(self.action_tool.strip()) > _MAX_ID:
            raise ProactiveIntelligenceError("action_tool must be 1-120 characters")
        if isinstance(self.cooldown_seconds, bool) or not isinstance(self.cooldown_seconds, int):
            raise ProactiveIntelligenceError("cooldown_seconds must be an integer")
        if not 0 <= self.cooldown_seconds <= 604_800:
            raise ProactiveIntelligenceError("cooldown_seconds must be between 0 and 604800")
        if not isinstance(self.action_args, Mapping):
            raise ProactiveIntelligenceError("action_args must be an object")
        try:
            encoded = json.dumps(dict(self.action_args), sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ProactiveIntelligenceError("action_args must be finite JSON data") from exc
        if len(encoded.encode("utf-8")) > _MAX_ARGS_JSON:
            raise ProactiveIntelligenceError("action_args exceed proactive bound")


@dataclass(frozen=True)
class ActionProposal:
    proposal_id: str
    condition_id: str
    tool_name: str
    arguments: dict[str, Any]
    risk: str
    gate: str | None
    approval_required: bool
    execution_authorized: bool = False
    source_id: str = "manual"
    source_digest: str | None = None
    observation_digest: str = ""
    trusted_source: bool = False


@dataclass(frozen=True)
class ConditionEvaluation:
    condition_id: str
    matched: bool
    proposed: bool
    suppressed_reason: str | None
    proposal: ActionProposal | None
    observed_at: float
    observation_digest: str
    source_id: str = "manual"
    source_digest: str | None = None
    trusted_source: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProactiveConditionEngine:
    """Deterministic condition evaluator that can propose but never execute actions."""

    def __init__(self, state_path: str | Path, *, clock=time.time) -> None:
        self.state_path = Path(state_path)
        self._clock = clock

    @staticmethod
    def _comparable(value: Any) -> Any:
        if isinstance(value, bool) or value is None or isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            number = float(value)
            if not math.isfinite(number):
                raise ProactiveIntelligenceError("numeric observations must be finite")
            return number
        raise ProactiveIntelligenceError("observations must be scalar JSON values")

    @classmethod
    def _matches(cls, operator: str, observed: Any, threshold: Any) -> bool:
        left = cls._comparable(observed)
        right = cls._comparable(threshold)
        if operator in {"gt", "gte", "lt", "lte"}:
            if not isinstance(left, float) or not isinstance(right, float):
                raise ProactiveIntelligenceError("ordered comparisons require numeric values")
            if operator == "gt": return left > right
            if operator == "gte": return left >= right
            if operator == "lt": return left < right
            return left <= right
        if type(left) is not type(right):
            return operator == "ne"
        return left == right if operator == "eq" else left != right

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"schema_version": 1, "conditions": {}}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProactiveIntelligenceError("proactive state is unreadable; evaluation blocked") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("conditions"), dict):
            raise ProactiveIntelligenceError("proactive state schema is invalid; evaluation blocked")
        return payload

    def _save_state(self, payload: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        temporary = self.state_path.with_name(self.state_path.name + ".tmp")
        temporary.write_text(serialized, encoding="utf-8")
        os.replace(temporary, self.state_path)

    @staticmethod
    def _tool_metadata(tool_catalog: list[dict[str, Any]], name: str) -> tuple[str, str | None]:
        exact = [item for item in tool_catalog if item.get("name") == name]
        if len(exact) != 1:
            raise ProactiveIntelligenceError("action tool is not uniquely present in the current registry catalog")
        risk = str(exact[0].get("risk") or "read")
        if risk not in _ALLOWED_TOOL_RISKS:
            raise ProactiveIntelligenceError("action tool has unsupported risk classification")
        gate = exact[0].get("gate")
        return risk, str(gate) if gate is not None else None

    def evaluate(
        self,
        spec: ConditionSpec,
        observed_value: Any,
        *,
        tool_catalog: list[dict[str, Any]],
        source_id: str = "manual",
        source_digest: str | None = None,
        trusted_source: bool = False,
        observed_at: float | None = None,
    ) -> ConditionEvaluation:
        spec.validate()
        observed = self._comparable(observed_value)
        now = float(self._clock())
        if not math.isfinite(now) or now < 0:
            raise ProactiveIntelligenceError("clock returned an invalid timestamp")
        evidence_time = now if observed_at is None else float(observed_at)
        if not math.isfinite(evidence_time) or evidence_time < 0 or evidence_time > now + 5:
            raise ProactiveIntelligenceError("observation timestamp is invalid")
        source_id = str(source_id).strip() or "manual"
        matched = self._matches(spec.operator, observed, spec.threshold)
        observation_digest = hashlib.sha256(
            json.dumps(
                {
                    "condition_id": spec.condition_id,
                    "observed": observed,
                    "matched": matched,
                    "source_id": source_id,
                    "source_digest": source_digest,
                    "observed_at": evidence_time,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        state = self._load_state()
        conditions = state["conditions"]
        previous = conditions.get(spec.condition_id, {})
        previous_match = bool(previous.get("matched", False))
        last_proposed_at = previous.get("last_proposed_at")

        suppression: str | None = None
        proposed = False
        proposal: ActionProposal | None = None
        if matched:
            if spec.edge_triggered and previous_match:
                suppression = "edge_already_active"
            elif isinstance(last_proposed_at, (int, float)) and now - float(last_proposed_at) < spec.cooldown_seconds:
                suppression = "cooldown_active"
            else:
                risk, gate = self._tool_metadata(tool_catalog, spec.action_tool.strip())
                args = json.loads(json.dumps(dict(spec.action_args), allow_nan=False))
                seed = json.dumps(
                    {
                        "condition_id": spec.condition_id,
                        "tool": spec.action_tool.strip(),
                        "args": args,
                        "observation_digest": observation_digest,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                proposal_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
                proposal = ActionProposal(
                    proposal_id=proposal_id,
                    condition_id=spec.condition_id,
                    tool_name=spec.action_tool.strip(),
                    arguments=args,
                    risk=risk,
                    gate=gate,
                    approval_required=risk in {"execute", "external", "destructive"},
                    execution_authorized=False,
                    source_id=source_id,
                    source_digest=source_digest,
                    observation_digest=observation_digest,
                    trusted_source=bool(trusted_source),
                )
                proposed = True
                last_proposed_at = now

        conditions[spec.condition_id] = {
            "matched": matched,
            "last_observed_at": evidence_time,
            "last_observation_digest": observation_digest,
            "last_source_id": source_id,
            "last_source_digest": source_digest,
            "last_proposed_at": last_proposed_at,
        }
        self._save_state(state)
        return ConditionEvaluation(
            condition_id=spec.condition_id,
            matched=matched,
            proposed=proposed,
            suppressed_reason=suppression,
            proposal=proposal,
            observed_at=evidence_time,
            observation_digest=observation_digest,
            source_id=source_id,
            source_digest=source_digest,
            trusted_source=bool(trusted_source),
        )

    def evaluate_evidence(self, spec: ConditionSpec, evidence: Any, *, tool_catalog: list[dict[str, Any]]) -> ConditionEvaluation:
        now = float(self._clock())
        evidence.require_fresh(now)
        return self.evaluate(
            spec,
            evidence.value,
            tool_catalog=tool_catalog,
            source_id=evidence.source_id,
            source_digest=evidence.source_digest,
            trusted_source=evidence.trusted_for_dispatch,
            observed_at=evidence.observed_at,
        )

    def status(self) -> dict[str, Any]:
        state = self._load_state()
        return {"ok": True, "schema_version": state["schema_version"], "tracked_conditions": len(state["conditions"]), "execution_capability": False, "dispatch_boundary": "ToolRegistry/ApprovalSecurity", "source_binding": True}


__all__ = ["ActionProposal", "ConditionEvaluation", "ConditionSpec", "ProactiveConditionEngine", "ProactiveIntelligenceError"]
