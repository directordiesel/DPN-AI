from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Any, Callable


@dataclass(frozen=True)
class RepositoryFile:
    path: str
    size_bytes: int = 0
    language: str = "unknown"


@dataclass
class ValidationRun:
    command: str
    ok: bool
    output: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RepairAttempt:
    attempt: int
    diagnosis: str
    changed_paths: list[str] = field(default_factory=list)
    validations: list[ValidationRun] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "diagnosis": self.diagnosis,
            "changed_paths": list(self.changed_paths),
            "validations": [item.to_dict() for item in self.validations],
        }


Inspector = Callable[[str], list[RepositoryFile]]
Diagnoser = Callable[[str, list[ValidationRun], int], str]
Patcher = Callable[[str, str, int], list[str]]
Validator = Callable[[list[str]], list[ValidationRun]]


class RepositoryEngineer:
    """Bounded repository inspect/patch/validate/repair control loop.

    The model may propose diagnoses or edits, but this coordinator owns retry
    limits, path checks, validation requirements, and the final success verdict.
    """

    DEFAULT_VALIDATIONS = ["python -m compileall -q app tests", "pytest -q"]

    def __init__(
        self,
        inspector: Inspector,
        diagnoser: Diagnoser,
        patcher: Patcher,
        validator: Validator,
        *,
        max_attempts: int = 3,
    ):
        if not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        self.inspector = inspector
        self.diagnoser = diagnoser
        self.patcher = patcher
        self.validator = validator
        self.max_attempts = max_attempts

    @staticmethod
    def normalize_repo_path(path: str) -> str:
        raw = (path or "").replace("\\", "/").strip()
        posix = PurePosixPath(raw)
        if not raw or posix.is_absolute() or ".." in posix.parts:
            raise ValueError("repository path escapes repository root")
        normalized = str(posix)
        if normalized.startswith(".git/") or normalized == ".git":
            raise ValueError(".git metadata cannot be modified")
        return normalized

    @classmethod
    def validate_changed_paths(cls, paths: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for path in paths:
            safe = cls.normalize_repo_path(path)
            if safe in seen:
                continue
            normalized.append(safe)
            seen.add(safe)
        return normalized

    def inspect(self, objective: str) -> list[RepositoryFile]:
        files = self.inspector(objective)
        if not isinstance(files, list):
            raise TypeError("inspector must return a list")
        clean: list[RepositoryFile] = []
        for item in files:
            if not isinstance(item, RepositoryFile):
                raise TypeError("inspector entries must be RepositoryFile")
            self.normalize_repo_path(item.path)
            clean.append(item)
        return clean

    def run(self, objective: str, validations: list[str] | None = None) -> dict[str, Any]:
        if not objective.strip():
            raise ValueError("objective is required")
        inventory = self.inspect(objective)
        validation_commands = [str(item).strip() for item in (validations or self.DEFAULT_VALIDATIONS) if str(item).strip()]
        if not validation_commands:
            raise ValueError("at least one validation command is required")

        attempts: list[RepairAttempt] = []
        previous_results: list[ValidationRun] = []

        for attempt in range(1, self.max_attempts + 1):
            diagnosis = self.diagnoser(objective, list(previous_results), attempt)
            changed = self.validate_changed_paths(self.patcher(objective, diagnosis, attempt))
            results = self.validator(validation_commands)
            if not isinstance(results, list) or any(not isinstance(item, ValidationRun) for item in results):
                raise TypeError("validator must return ValidationRun entries")
            if len(results) != len(validation_commands):
                raise ValueError("validator did not return a result for every required validation command")

            attempts.append(RepairAttempt(
                attempt=attempt,
                diagnosis=str(diagnosis)[:4000],
                changed_paths=changed,
                validations=results,
            ))
            previous_results = results
            if all(item.ok for item in results):
                return {
                    "ok": True,
                    "objective": objective,
                    "inventory": [asdict(item) for item in inventory],
                    "attempts": [item.to_dict() for item in attempts],
                    "changed_paths": list(dict.fromkeys(path for item in attempts for path in item.changed_paths)),
                    "validation_commands": validation_commands,
                }

        return {
            "ok": False,
            "objective": objective,
            "inventory": [asdict(item) for item in inventory],
            "attempts": [item.to_dict() for item in attempts],
            "changed_paths": list(dict.fromkeys(path for item in attempts for path in item.changed_paths)),
            "validation_commands": validation_commands,
            "failure": "validation remained red after bounded repair attempts",
        }
