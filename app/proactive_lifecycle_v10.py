from __future__ import annotations

import json
import math
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from app.proactive_intelligence_v10 import ConditionEvaluation, ConditionSpec, ProactiveConditionEngine, ProactiveIntelligenceError
from app.proactive_sources_v10 import ProactiveSourceRegistry


class ProactiveLifecycleError(ValueError):
    """Raised when persistent proactive lifecycle state cannot be trusted."""


_MAX_DEFINITIONS = 256
_MAX_INTERVAL_SECONDS = 86_400
_MIN_INTERVAL_SECONDS = 30


@dataclass(frozen=True)
class ConditionDefinition:
    condition_id: str
    source_id: str
    operator: str
    threshold: Any
    action_tool: str
    action_args: dict[str, Any]
    interval_seconds: int = 300
    cooldown_seconds: int = 300
    edge_triggered: bool = True
    enabled: bool = False
    created_at: float = 0.0
    updated_at: float = 0.0
    next_due_at: float = 0.0

    def to_spec(self) -> ConditionSpec:
        spec = ConditionSpec(
            condition_id=self.condition_id,
            operator=self.operator,
            threshold=self.threshold,
            action_tool=self.action_tool,
            action_args=dict(self.action_args),
            cooldown_seconds=self.cooldown_seconds,
            edge_triggered=self.edge_triggered,
        )
        spec.validate()
        return spec

    def validate(self) -> None:
        self.to_spec()
        source_id = self.source_id.strip()
        if not source_id or len(source_id) > 120:
            raise ProactiveLifecycleError("source_id must be 1-120 characters")
        if isinstance(self.interval_seconds, bool) or not isinstance(self.interval_seconds, int):
            raise ProactiveLifecycleError("interval_seconds must be an integer")
        if not _MIN_INTERVAL_SECONDS <= self.interval_seconds <= _MAX_INTERVAL_SECONDS:
            raise ProactiveLifecycleError("interval_seconds must be between 30 and 86400")
        for field_name, value in (("created_at", self.created_at), ("updated_at", self.updated_at), ("next_due_at", self.next_due_at)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0:
                raise ProactiveLifecycleError(f"{field_name} must be a finite non-negative timestamp")


@dataclass(frozen=True)
class LifecycleRunResult:
    condition_id: str
    evaluated: bool
    skipped_reason: str | None
    evaluation: ConditionEvaluation | None
    next_due_at: float

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.evaluation is not None:
            payload["evaluation"] = self.evaluation.to_dict()
        return payload


class ProactiveConditionLifecycle:
    """Durable condition-definition lifecycle without an independent scheduler.

    The host calls ``evaluate_due`` from its existing background/automation loop.
    This class never dispatches a proposal and never grants permissions.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        engine: ProactiveConditionEngine,
        sources: ProactiveSourceRegistry,
        tool_catalog: Callable[[], list[dict[str, Any]]],
        proposal_sink: Callable[[ConditionEvaluation, Any], None] | None = None,
        clock=time.time,
    ) -> None:
        self.path = Path(path)
        self.engine = engine
        self.sources = sources
        self.tool_catalog = tool_catalog
        self.proposal_sink = proposal_sink
        self._clock = clock

    def _now(self) -> float:
        value = float(self._clock())
        if not math.isfinite(value) or value < 0:
            raise ProactiveLifecycleError("clock returned an invalid timestamp")
        return value

    def _empty(self) -> dict[str, Any]:
        return {"schema_version": 1, "definitions": {}}

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProactiveLifecycleError("proactive lifecycle state is unreadable; lifecycle operations blocked") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("definitions"), dict):
            raise ProactiveLifecycleError("proactive lifecycle state schema is invalid; lifecycle operations blocked")
        if len(payload["definitions"]) > _MAX_DEFINITIONS:
            raise ProactiveLifecycleError("proactive lifecycle definition bound exceeded")
        for condition_id, raw in payload["definitions"].items():
            if not isinstance(raw, dict) or raw.get("condition_id") != condition_id:
                raise ProactiveLifecycleError("proactive lifecycle definition identity is invalid")
            try:
                ConditionDefinition(**raw).validate()
            except (TypeError, ProactiveIntelligenceError, ProactiveLifecycleError) as exc:
                raise ProactiveLifecycleError(f"proactive lifecycle definition is invalid: {condition_id}") from exc
        return payload

    def _save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, self.path)

    def list_definitions(self) -> list[ConditionDefinition]:
        state = self._load()
        return [ConditionDefinition(**raw) for _, raw in sorted(state["definitions"].items())]

    def get(self, condition_id: str) -> ConditionDefinition | None:
        state = self._load()
        raw = state["definitions"].get(str(condition_id).strip())
        return ConditionDefinition(**raw) if raw is not None else None

    def register(
        self,
        *,
        condition_id: str,
        source_id: str,
        operator: str,
        threshold: Any,
        action_tool: str,
        action_args: dict[str, Any] | None = None,
        interval_seconds: int = 300,
        cooldown_seconds: int = 300,
        edge_triggered: bool = True,
    ) -> ConditionDefinition:
        state = self._load()
        condition_id = str(condition_id).strip()
        if condition_id in state["definitions"]:
            raise ProactiveLifecycleError("condition definition already exists")
        if len(state["definitions"]) >= _MAX_DEFINITIONS:
            raise ProactiveLifecycleError("proactive lifecycle definition bound reached")
        known_sources = {item["source_id"] for item in self.sources.catalog()}
        if str(source_id).strip() not in known_sources:
            raise ProactiveLifecycleError("source_id is not registered by the host")
        now = self._now()
        definition = ConditionDefinition(
            condition_id=condition_id,
            source_id=str(source_id).strip(),
            operator=operator,
            threshold=threshold,
            action_tool=str(action_tool).strip(),
            action_args=dict(action_args or {}),
            interval_seconds=interval_seconds,
            cooldown_seconds=cooldown_seconds,
            edge_triggered=bool(edge_triggered),
            enabled=False,
            created_at=now,
            updated_at=now,
            next_due_at=now,
        )
        definition.validate()
        state["definitions"][condition_id] = asdict(definition)
        self._save(state)
        return definition

    def set_enabled(self, condition_id: str, enabled: bool) -> ConditionDefinition:
        state = self._load()
        key = str(condition_id).strip()
        raw = state["definitions"].get(key)
        if raw is None:
            raise ProactiveLifecycleError("condition definition does not exist")
        now = self._now()
        updated = ConditionDefinition(
            **{
                **raw,
                "enabled": bool(enabled),
                "updated_at": now,
                "next_due_at": now if enabled else float(raw["next_due_at"]),
            }
        )
        updated.validate()
        state["definitions"][key] = asdict(updated)
        self._save(state)
        return updated

    def evaluate_due(self, *, limit: int = 32) -> list[LifecycleRunResult]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 64:
            raise ProactiveLifecycleError("evaluation limit must be between 1 and 64")
        state = self._load()
        now = self._now()
        results: list[LifecycleRunResult] = []
        changed = False
        for key in sorted(state["definitions"]):
            if len(results) >= limit:
                break
            definition = ConditionDefinition(**state["definitions"][key])
            if not definition.enabled:
                continue
            if definition.next_due_at > now:
                continue
            try:
                evidence = self.sources.collect(definition.source_id)
                evaluation = self.engine.evaluate_evidence(
                    definition.to_spec(),
                    evidence,
                    tool_catalog=self.tool_catalog(),
                )
                if evaluation.proposal is not None and self.proposal_sink is not None:
                    self.proposal_sink(evaluation, evidence)
                next_due = now + definition.interval_seconds
                results.append(LifecycleRunResult(key, True, None, evaluation, next_due))
            except Exception as exc:
                # Source/engine failures remain visible and retry only at the next bounded interval.
                next_due = now + definition.interval_seconds
                results.append(LifecycleRunResult(key, False, type(exc).__name__, None, next_due))
            state["definitions"][key] = asdict(
                ConditionDefinition(
                    **{
                        **state["definitions"][key],
                        "updated_at": now,
                        "next_due_at": next_due,
                    }
                )
            )
            changed = True
        if changed:
            self._save(state)
        return results

    def status(self) -> dict[str, Any]:
        definitions = self.list_definitions()
        return {
            "ok": True,
            "schema_version": 1,
            "definitions": len(definitions),
            "enabled": sum(1 for item in definitions if item.enabled),
            "max_definitions": _MAX_DEFINITIONS,
            "scheduler_owned": False,
            "dispatch_capability": False,
            "default_new_definition_enabled": False,
        }


__all__ = [
    "ConditionDefinition",
    "LifecycleRunResult",
    "ProactiveConditionLifecycle",
    "ProactiveLifecycleError",
]
