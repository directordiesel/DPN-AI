from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping


class EvaluationStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    domain: str
    critical: bool = True
    weight: int = 1

    def validate(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id is required")
        if not self.domain.strip():
            raise ValueError("domain is required")
        if isinstance(self.weight, bool) or not isinstance(self.weight, int) or self.weight <= 0:
            raise ValueError("weight must be a positive integer")


@dataclass(frozen=True)
class EvaluationResult:
    case_id: str
    status: EvaluationStatus
    evidence: str = ""


@dataclass(frozen=True)
class GateReport:
    passed: bool
    weighted_score: float
    passed_cases: int
    failed_cases: int
    skipped_cases: int
    critical_failures: tuple[str, ...]
    missing_cases: tuple[str, ...]
    domain_scores: Mapping[str, float]


class V9EvaluationGate:
    """Deterministic production-readiness gate for DPN AI v9.

    The gate is intentionally policy-only: test runners supply case results and
    this class decides whether the build is releasable. Critical cases can never
    be waived by aggregate score, skipped/missing critical cases fail closed,
    and duplicate or unknown results are rejected.
    """

    def __init__(self, cases: Iterable[EvaluationCase], *, minimum_score: float = 0.95) -> None:
        if not 0 < float(minimum_score) <= 1:
            raise ValueError("minimum_score must be in (0, 1]")
        built: dict[str, EvaluationCase] = {}
        for case in cases:
            case.validate()
            if case.case_id in built:
                raise ValueError(f"duplicate evaluation case: {case.case_id}")
            built[case.case_id] = case
        if not built:
            raise ValueError("at least one evaluation case is required")
        self.cases = built
        self.minimum_score = float(minimum_score)

    def evaluate(self, results: Iterable[EvaluationResult]) -> GateReport:
        seen: dict[str, EvaluationResult] = {}
        for result in results:
            if result.case_id not in self.cases:
                raise ValueError(f"unknown evaluation case: {result.case_id}")
            if result.case_id in seen:
                raise ValueError(f"duplicate evaluation result: {result.case_id}")
            seen[result.case_id] = result

        missing = tuple(sorted(set(self.cases) - set(seen)))
        passed = failed = skipped = 0
        numerator = denominator = 0
        critical_failures: list[str] = []
        domain_totals: dict[str, int] = {}
        domain_passed: dict[str, int] = {}

        for case_id, case in self.cases.items():
            result = seen.get(case_id)
            domain_totals[case.domain] = domain_totals.get(case.domain, 0) + case.weight
            denominator += case.weight
            if result is None:
                if case.critical:
                    critical_failures.append(case_id)
                continue
            if result.status == EvaluationStatus.PASS:
                passed += 1
                numerator += case.weight
                domain_passed[case.domain] = domain_passed.get(case.domain, 0) + case.weight
            elif result.status == EvaluationStatus.FAIL:
                failed += 1
                if case.critical:
                    critical_failures.append(case_id)
            elif result.status == EvaluationStatus.SKIP:
                skipped += 1
                if case.critical:
                    critical_failures.append(case_id)
            else:  # pragma: no cover - Enum normally prevents this path
                raise ValueError(f"invalid evaluation status for {case_id}")

        weighted_score = numerator / denominator if denominator else 0.0
        domain_scores = {
            domain: domain_passed.get(domain, 0) / total
            for domain, total in sorted(domain_totals.items())
        }
        gate_passed = not critical_failures and not missing and weighted_score >= self.minimum_score
        return GateReport(
            passed=gate_passed,
            weighted_score=weighted_score,
            passed_cases=passed,
            failed_cases=failed,
            skipped_cases=skipped,
            critical_failures=tuple(sorted(set(critical_failures))),
            missing_cases=missing,
            domain_scores=domain_scores,
        )


def default_v9_cases() -> tuple[EvaluationCase, ...]:
    """Release-critical coverage expected before the v9 RC can be promoted."""
    return (
        EvaluationCase("intelligence.plan_execute_review", "intelligence", True, 2),
        EvaluationCase("coding.repo_change_safety", "coding", True, 2),
        EvaluationCase("permissions.dangerous_action_gate", "permissions", True, 3),
        EvaluationCase("memory.rag_source_scope", "memory", True, 2),
        EvaluationCase("research.untrusted_content_isolation", "research", True, 2),
        EvaluationCase("artifacts.integrity_validation", "artifacts", True, 2),
        EvaluationCase("image.provider_fail_closed", "media", True, 1),
        EvaluationCase("automation.approval_dependency", "automation", True, 2),
        EvaluationCase("voice.workspace_boundary", "voice", True, 1),
        EvaluationCase("desktop.evidence_first_controls", "desktop", False, 1),
        EvaluationCase("mobile.device_trust_revocation", "mobile", True, 2),
        EvaluationCase("models.local_first_remote_deny", "models", True, 3),
        EvaluationCase("security.secret_and_injection_boundary", "security", True, 4),
        EvaluationCase("recovery.snapshot_integrity", "recovery", True, 3),
        EvaluationCase("sdk.write_idempotency_and_approval", "sdk", True, 2),
    )


__all__ = [
    "EvaluationCase",
    "EvaluationResult",
    "EvaluationStatus",
    "GateReport",
    "V9EvaluationGate",
    "default_v9_cases",
]
