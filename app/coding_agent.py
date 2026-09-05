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


@dataclass(frozen=True)
class RepositoryEntry:
    path: str
    dependencies: tuple[str, ...] = ()
    kind: str = "source"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "dependencies": list(self.dependencies),
            "kind": self.kind,
        }


class CodingAgentPlanner:
    """Deterministic guardrails for repo-wide coding missions.

    The model may propose edits, but this planner validates paths, actions,
    validation expectations and dependency ordering before execution. The
    repository-map helpers intentionally operate on caller-supplied metadata so
    they remain deterministic, auditable, and independent from model guesses.
    """

    ALLOWED_ACTIONS = {"create", "update", "delete"}
    FORBIDDEN_PARTS = {".git", ".github/secrets", "node_modules", ".venv", "venv"}
    TEST_KINDS = {"test", "tests"}

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

    @classmethod
    def build_repository_map(cls, entries: list[dict[str, Any]]) -> dict[str, RepositoryEntry]:
        """Normalize repository metadata into a deterministic path-indexed map.

        Entries may be produced by repository scanning or another trusted
        indexer. Dependencies that are not present in the map are retained so
        callers can distinguish external/unknown references during impact
        analysis.
        """
        repository_map: dict[str, RepositoryEntry] = {}
        for raw_entry in entries:
            path = cls.normalize_path(str(raw_entry.get("path") or ""))
            if path in repository_map:
                raise ValueError(f"duplicate repository entry: {path}")

            dependencies: list[str] = []
            for dependency in raw_entry.get("dependencies") or []:
                normalized = cls.normalize_path(str(dependency))
                if normalized == path:
                    continue
                if normalized not in dependencies:
                    dependencies.append(normalized)

            kind = str(raw_entry.get("kind") or "source").strip().lower() or "source"
            repository_map[path] = RepositoryEntry(
                path=path,
                dependencies=tuple(dependencies),
                kind=kind,
            )
        return repository_map

    @classmethod
    def analyze_change_impact(
        cls,
        changes: list[CodeChange],
        repository_map: dict[str, RepositoryEntry],
    ) -> dict[str, Any]:
        """Return changed paths plus transitive in-repository dependants."""
        changed = {change.path for change in changes}
        affected = set(changed)
        unknown_changed = sorted(path for path in changed if path not in repository_map)

        reverse_dependencies: dict[str, set[str]] = {}
        for entry in repository_map.values():
            for dependency in entry.dependencies:
                reverse_dependencies.setdefault(dependency, set()).add(entry.path)

        queue = list(changed)
        while queue:
            current = queue.pop(0)
            for dependant in sorted(reverse_dependencies.get(current, set())):
                if dependant not in affected:
                    affected.add(dependant)
                    queue.append(dependant)

        impacted_tests = sorted(
            path
            for path in affected
            if path in repository_map and cls._is_test_entry(repository_map[path])
        )
        return {
            "changed": sorted(changed),
            "affected": sorted(affected),
            "dependants": sorted(affected - changed),
            "targeted_tests": impacted_tests,
            "unknown_changed": unknown_changed,
        }

    @classmethod
    def select_targeted_tests(
        cls,
        changes: list[CodeChange],
        repository_map: dict[str, RepositoryEntry],
        *,
        max_tests: int = 50,
    ) -> list[str]:
        """Select known tests affected by the proposed change set.

        Only tests that exist in the supplied repository map are returned; this
        deliberately avoids inventing test paths that may not exist.
        """
        if max_tests < 1:
            raise ValueError("max_tests must be at least 1")
        impact = cls.analyze_change_impact(changes, repository_map)
        return impact["targeted_tests"][:max_tests]

    @classmethod
    def build_patch_plan(
        cls,
        changes: list[CodeChange],
        repository_map: dict[str, RepositoryEntry],
    ) -> dict[str, Any]:
        """Build an auditable execution plan with impact and validation data."""
        impact = cls.analyze_change_impact(changes, repository_map)
        validations: list[str] = []
        for change in changes:
            for validation in change.validation:
                if validation not in validations:
                    validations.append(validation)
        return {
            "summary": cls.summarize(changes),
            "impact": impact,
            "targeted_tests": cls.select_targeted_tests(changes, repository_map),
            "validation": validations,
            "unknown_paths_require_review": bool(impact["unknown_changed"]),
        }

    @classmethod
    def self_review(
        cls,
        changes: list[CodeChange],
        actual_changed_paths: list[str],
        check_results: dict[str, bool],
    ) -> dict[str, Any]:
        """Compare planned edits with observed edits and validation evidence."""
        planned = {change.path for change in changes}
        actual = {cls.normalize_path(path) for path in actual_changed_paths}
        missing = sorted(planned - actual)
        unexpected = sorted(actual - planned)
        failed_checks = sorted(name for name, passed in check_results.items() if not bool(passed))
        required_evidence = sorted({item for change in changes for item in change.validation})
        missing_evidence = sorted(item for item in required_evidence if item not in check_results)
        requires_approval = any(change.action == "delete" or change.risk == "high" for change in changes)
        passed = not missing and not unexpected and not failed_checks and not missing_evidence
        return {
            "passed": passed,
            "planned_paths": sorted(planned),
            "actual_paths": sorted(actual),
            "missing_planned_changes": missing,
            "unexpected_changes": unexpected,
            "failed_checks": failed_checks,
            "missing_evidence": missing_evidence,
            "requires_approval": requires_approval,
        }

    @classmethod
    def _is_test_entry(cls, entry: RepositoryEntry) -> bool:
        name = PurePosixPath(entry.path).name.lower()
        return (
            entry.kind in cls.TEST_KINDS
            or entry.path.startswith("tests/")
            or name.startswith("test_")
            or name.endswith("_test.py")
        )

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
