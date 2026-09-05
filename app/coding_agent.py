from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import PurePosixPath
from typing import Any


@dataclass(frozen=True)
class CodeChange:
    path: str
    action: str
    rationale: str
    validation: list[str]
    risk: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CodingAgentPlanner:
    """Deterministic guardrails for repo-wide coding missions.

    The model may propose edits, but this planner validates paths, actions,
    validation expectations and dependency ordering before execution.
    """

    ALLOWED_ACTIONS = {"create", "update", "delete"}
    FORBIDDEN_PARTS = {".git", ".github/secrets", "node_modules", ".venv", "venv"}

    @classmethod
    def normalize_path(cls, value: str) -> str:
        raw = (value or "").replace("\\", "/").strip()
        path = PurePosixPath(raw)
        if not raw or path.is_absolute() or ".." in path.parts:
            raise ValueError("path must remain inside the repository")
        normalized = str(path)
        if any(part in normalized for part in cls.FORBIDDEN_PARTS):
            raise ValueError(f"protected path is not editable: {normalized}")
        return normalized

    @classmethod
    def build_change_set(cls, proposals: list[dict[str, Any]]) -> list[CodeChange]:
        changes: list[CodeChange] = []
        seen: set[str] = set()
        for proposal in proposals:
            path = cls.normalize_path(str(proposal.get("path") or ""))
            if path in seen:
                raise ValueError(f"duplicate change for path: {path}")
            action = str(proposal.get("action") or "update").lower()
            if action not in cls.ALLOWED_ACTIONS:
                raise ValueError(f"unsupported action: {action}")
            validation = [str(item) for item in proposal.get("validation") or [] if str(item).strip()]
            if action in {"create", "update"} and not validation:
                validation = ["syntax_or_compile_check", "targeted_tests"]
            risk = str(proposal.get("risk") or "low").lower()
            if risk not in {"low", "medium", "high"}:
                risk = "medium"
            if action == "delete" and risk == "low":
                risk = "medium"
            changes.append(CodeChange(
                path=path,
                action=action,
                rationale=str(proposal.get("rationale") or "requested code change")[:2000],
                validation=validation[:10],
                risk=risk,
            ))
            seen.add(path)
        return changes

    @staticmethod
    def summarize(changes: list[CodeChange]) -> dict[str, Any]:
        return {
            "count": len(changes),
            "creates": sum(change.action == "create" for change in changes),
            "updates": sum(change.action == "update" for change in changes),
            "deletes": sum(change.action == "delete" for change in changes),
            "high_risk": [change.path for change in changes if change.risk == "high"],
            "requires_approval": any(change.action == "delete" or change.risk == "high" for change in changes),
            "changes": [change.to_dict() for change in changes],
        }
