from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable


class StepStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class ReviewVerdict(str, Enum):
    PASS = "pass"
    RETRY = "retry"
    FAIL = "fail"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2
    retryable_errors: tuple[str, ...] = ("timeout", "temporary", "rate_limit", "transient")

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")

    def allows(self, error: str, attempt: int) -> bool:
        if attempt >= self.max_attempts:
            return False
        lowered = (error or "").lower()
        return any(marker in lowered for marker in self.retryable_errors)


@dataclass
class StepResult:
    ok: bool
    output: Any = None
    error: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    generated_files: list[str] = field(default_factory=list)
    tool_count: int = 0


@dataclass
class ReviewResult:
    verdict: ReviewVerdict
    reason: str
    confidence: float = 1.0

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, float(self.confidence)))


@dataclass
class PlanStep:
    id: str
    title: str
    instructions: str
    role: str = "director"
    dependencies: list[str] = field(default_factory=list)
    evidence_required: list[str] = field(default_factory=lambda: ["concrete result", "limitations"])
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0
    result: StepResult | None = None
    review: ReviewResult | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        if self.review:
            data["review"]["verdict"] = self.review.verdict.value
        return data


@dataclass
class ReasoningPlan:
    objective: str
    steps: list[PlanStep]
    success_criteria: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.objective.strip():
            raise ValueError("objective is required")
        if not self.steps:
            raise ValueError("at least one plan step is required")
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step ids must be unique")
        known = set(ids)
        for index, step in enumerate(self.steps):
            if not step.id.strip():
                raise ValueError("step id is required")
            if step.id in step.dependencies:
                raise ValueError(f"step {step.id} cannot depend on itself")
            unknown = [dep for dep in step.dependencies if dep not in known]
            if unknown:
                raise ValueError(f"step {step.id} has unknown dependencies: {unknown}")
            prior = set(ids[:index])
            forward = [dep for dep in step.dependencies if dep not in prior]
            if forward:
                raise ValueError(f"step {step.id} depends on non-prior steps: {forward}")


Executor = Callable[[PlanStep, dict[str, StepResult]], StepResult]
Reviewer = Callable[[PlanStep, StepResult], ReviewResult]


class IntelligenceRuntime:
    """Deterministic planner/executor/reviewer control plane for DPN AI v9.

    Model-generated reasoning may propose a plan, but this runtime owns execution
    order, dependency enforcement, retry limits, evidence collection and review
    decisions. That separation prevents a model from bypassing orchestration
    rules merely by claiming a step succeeded.
    """

    def __init__(self, executor: Executor, reviewer: Reviewer | None = None):
        self.executor = executor
        self.reviewer = reviewer or self._default_reviewer

    @staticmethod
    def _default_reviewer(step: PlanStep, result: StepResult) -> ReviewResult:
        if not result.ok:
            return ReviewResult(ReviewVerdict.FAIL, result.error or "executor reported failure", 1.0)
        if step.evidence_required and not result.evidence and not result.generated_files:
            return ReviewResult(ReviewVerdict.RETRY, "required evidence was not produced", 0.9)
        return ReviewResult(ReviewVerdict.PASS, "execution produced observable evidence", 0.95)

    @staticmethod
    def from_normalized_plan(plan: dict[str, Any]) -> ReasoningPlan:
        raw_steps = plan.get("steps") if isinstance(plan, dict) else None
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError("normalized plan has no steps")
        steps: list[PlanStep] = []
        ids: list[str] = []
        for index, raw in enumerate(raw_steps):
            step_id = str(raw.get("id") or f"step-{index + 1}")
            dependency_ids: list[str] = []
            for dependency in raw.get("dependencies") or []:
                if isinstance(dependency, int) and 0 <= dependency < len(ids):
                    dependency_ids.append(ids[dependency])
                elif isinstance(dependency, str):
                    dependency_ids.append(dependency)
            attempts = max(1, min(int(raw.get("max_attempts", 2)), 10))
            step = PlanStep(
                id=step_id,
                title=str(raw.get("title") or f"Step {index + 1}"),
                instructions=str(raw.get("instructions") or ""),
                role=str(raw.get("role") or "director"),
                dependencies=list(dict.fromkeys(dependency_ids)),
                evidence_required=[str(item) for item in (raw.get("evidence_required") or ["concrete result", "limitations"])],
                retry_policy=RetryPolicy(max_attempts=attempts),
            )
            steps.append(step)
            ids.append(step_id)
        objective = str((plan.get("contract") or {}).get("objective") or plan.get("summary") or "Execute plan")
        result = ReasoningPlan(objective=objective, steps=steps, success_criteria=list(plan.get("success_criteria") or []))
        result.validate()
        return result

    @staticmethod
    def _dependencies_succeeded(step: PlanStep, completed: dict[str, StepResult]) -> bool:
        return all(dep in completed and completed[dep].ok for dep in step.dependencies)

    def run(self, plan: ReasoningPlan) -> dict[str, Any]:
        plan.validate()
        completed: dict[str, StepResult] = {}
        timeline: list[dict[str, Any]] = []

        for step in plan.steps:
            if not self._dependencies_succeeded(step, completed):
                step.status = StepStatus.BLOCKED
                timeline.append({"step_id": step.id, "event": "blocked", "dependencies": list(step.dependencies)})
                continue

            step.status = StepStatus.READY
            while step.attempts < step.retry_policy.max_attempts:
                step.attempts += 1
                step.status = StepStatus.RUNNING
                timeline.append({"step_id": step.id, "event": "attempt_started", "attempt": step.attempts})

                try:
                    result = self.executor(step, dict(completed))
                    if not isinstance(result, StepResult):
                        raise TypeError("executor must return StepResult")
                except Exception as exc:
                    result = StepResult(ok=False, error=f"executor_exception: {type(exc).__name__}: {exc}")

                review = self.reviewer(step, result)
                if not isinstance(review, ReviewResult):
                    raise TypeError("reviewer must return ReviewResult")
                step.result = result
                step.review = review
                timeline.append({
                    "step_id": step.id,
                    "event": "reviewed",
                    "attempt": step.attempts,
                    "verdict": review.verdict.value,
                    "confidence": review.confidence,
                    "reason": review.reason,
                })

                if review.verdict == ReviewVerdict.PASS and result.ok:
                    step.status = StepStatus.SUCCEEDED
                    completed[step.id] = result
                    break

                retry_requested = review.verdict == ReviewVerdict.RETRY
                retryable_error = step.retry_policy.allows(result.error, step.attempts)
                evidence_retry = retry_requested and step.attempts < step.retry_policy.max_attempts
                if retryable_error or evidence_retry:
                    timeline.append({"step_id": step.id, "event": "retry_scheduled", "attempt": step.attempts})
                    continue

                step.status = StepStatus.FAILED
                break

        failed = [step.id for step in plan.steps if step.status == StepStatus.FAILED]
        blocked = [step.id for step in plan.steps if step.status == StepStatus.BLOCKED]
        succeeded = [step.id for step in plan.steps if step.status == StepStatus.SUCCEEDED]
        return {
            "ok": not failed and not blocked and len(succeeded) == len(plan.steps),
            "objective": plan.objective,
            "succeeded": succeeded,
            "failed": failed,
            "blocked": blocked,
            "steps": [step.to_dict() for step in plan.steps],
            "timeline": timeline,
        }
