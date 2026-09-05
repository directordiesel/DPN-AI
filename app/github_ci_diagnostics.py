from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class CIDiagnosis:
    category: str
    confidence: float
    retryable: bool
    summary: str
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GitHubCIDiagnostics:
    """Classify GitHub Actions failures before an agent attempts a repair."""

    INFRA_MARKERS = (
        "failed to start runner", "runner lost communication", "no space left on device",
        "service unavailable", "internal server error", "job was not acquired",
    )
    DEPENDENCY_MARKERS = (
        "could not find a version", "dependency resolution", "package not found",
        "failed to download", "connection reset", "rate limit",
    )
    TEST_MARKERS = ("assertionerror", "tests failed", "failed test", "pytest", "test failure")
    COMPILE_MARKERS = ("syntaxerror", "compile error", "compilation failed", "cannot find symbol", "type error")
    SECURITY_MARKERS = ("secret", "credential", "security gate", "vulnerability", "permission denied")

    @classmethod
    def classify(cls, job_name: str, conclusion: str, logs: str | None = None, steps: list[dict[str, Any]] | None = None) -> CIDiagnosis:
        text = " ".join([job_name or "", conclusion or "", logs or ""]).lower()
        failed_steps = [str(step.get("name") or "") for step in (steps or []) if str(step.get("conclusion") or "").lower() == "failure"]
        if any(marker in text for marker in cls.SECURITY_MARKERS):
            return CIDiagnosis("security", 0.92, False, "security or authorization validation failed", "inspect the exact security finding; do not bypass the gate")
        if any(marker in text for marker in cls.INFRA_MARKERS):
            return CIDiagnosis("infrastructure", 0.9, True, "runner or GitHub infrastructure failure is likely", "retry the failed job once before changing source code")
        if any(marker in text for marker in cls.COMPILE_MARKERS):
            return CIDiagnosis("compile", 0.9, False, "source compilation or type validation failed", "inspect the failing compiler output and patch the implicated source")
        if any(marker in text for marker in cls.TEST_MARKERS):
            return CIDiagnosis("test", 0.86, False, "automated tests failed", "identify the first causal test failure, reproduce it, then patch and rerun targeted tests")
        if any(marker in text for marker in cls.DEPENDENCY_MARKERS):
            return CIDiagnosis("dependency", 0.78, True, "dependency installation or remote package retrieval failed", "confirm package metadata and retry transient network failures before editing code")
        if failed_steps:
            return CIDiagnosis("workflow_step", 0.62, False, f"workflow failed in step(s): {', '.join(failed_steps[:3])}", "inspect logs for the first failed step before proposing a source change")
        if (conclusion or "").lower() in {"cancelled", "timed_out"}:
            return CIDiagnosis("execution", 0.7, True, f"workflow ended as {conclusion}", "retry once and inspect runner/resource behavior if it repeats")
        return CIDiagnosis("unknown", 0.35, False, "failure cause is not established from available evidence", "collect job steps and logs before attempting a repair")
