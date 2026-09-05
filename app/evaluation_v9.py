from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Callable, Iterable


MAX_EVALUATION_CASES = 1000
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/ -]{0,127}$")
_CATEGORIES = {"api", "artifact", "performance", "recovery", "regression", "security"}


class EvaluationError(ValueError):
    """Raised when deterministic evaluation inputs are invalid."""


@dataclass(frozen=True)
class EvaluationCase:
    name: str
    category: str
    check: Callable[[], bool]


@dataclass(frozen=True)
class EvaluationResult:
    name: str
    category: str
    status: str
    error_type: str | None = None


@dataclass(frozen=True)
class EvaluationSummary:
    total: int
    passed: int
    failed: int
    errors: int
    pass_rate: float
    results: tuple[EvaluationResult, ...]

    def payload(self) -> dict[str, object]:
        return asdict(self)


def run_evaluations(cases: Iterable[EvaluationCase], *, max_cases: int = MAX_EVALUATION_CASES) -> EvaluationSummary:
    if isinstance(max_cases, bool) or not isinstance(max_cases, int) or not 1 <= max_cases <= MAX_EVALUATION_CASES:
        raise EvaluationError(f"max_cases must be between 1 and {MAX_EVALUATION_CASES}")

    values = tuple(cases)
    if len(values) > max_cases:
        raise EvaluationError("evaluation case count exceeds configured limit")

    seen: set[str] = set()
    results: list[EvaluationResult] = []
    passed = failed = errors = 0

    for case in values:
        if not isinstance(case, EvaluationCase):
            raise EvaluationError("all evaluation entries must be EvaluationCase values")
        name = str(case.name or "").strip()
        category = str(case.category or "").strip().lower()
        if not _NAME_RE.fullmatch(name):
            raise EvaluationError("evaluation case name is invalid")
        if name in seen:
            raise EvaluationError(f"duplicate evaluation case name: {name}")
        seen.add(name)
        if category not in _CATEGORIES:
            raise EvaluationError(f"unsupported evaluation category: {category}")
        if not callable(case.check):
            raise EvaluationError(f"evaluation check is not callable: {name}")

        try:
            ok = case.check()
            if not isinstance(ok, bool):
                raise TypeError("evaluation checks must return bool")
            if ok:
                passed += 1
                results.append(EvaluationResult(name=name, category=category, status="pass"))
            else:
                failed += 1
                results.append(EvaluationResult(name=name, category=category, status="fail"))
        except Exception as exc:  # noqa: BLE001
            errors += 1
            # Deliberately expose only the exception type. Evaluation diagnostics
            # must not accidentally serialize prompts, credentials, paths, or
            # provider response bodies from arbitrary checks.
            results.append(
                EvaluationResult(
                    name=name,
                    category=category,
                    status="error",
                    error_type=type(exc).__name__,
                )
            )

    total = len(results)
    pass_rate = (passed / total) if total else 1.0
    return EvaluationSummary(
        total=total,
        passed=passed,
        failed=failed,
        errors=errors,
        pass_rate=pass_rate,
        results=tuple(results),
    )


__all__ = [
    "EvaluationCase",
    "EvaluationError",
    "EvaluationResult",
    "EvaluationSummary",
    "MAX_EVALUATION_CASES",
    "run_evaluations",
]
