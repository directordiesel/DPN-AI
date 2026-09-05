from app.intelligence_runtime import (
    IntelligenceRuntime,
    PlanStep,
    ReasoningPlan,
    ReviewResult,
    ReviewVerdict,
    RetryPolicy,
    StepResult,
    StepStatus,
)


def test_reasoning_plan_rejects_forward_dependencies():
    plan = ReasoningPlan(
        objective="test",
        steps=[
            PlanStep(id="first", title="First", instructions="x", dependencies=["second"]),
            PlanStep(id="second", title="Second", instructions="y"),
        ],
    )
    try:
        plan.validate()
    except ValueError as exc:
        assert "non-prior" in str(exc)
    else:
        raise AssertionError("forward dependency was accepted")


def test_runtime_executes_dependencies_and_collects_evidence():
    observed = []

    def executor(step, completed):
        observed.append((step.id, sorted(completed)))
        return StepResult(ok=True, evidence=[{"kind": "test", "step": step.id}], tool_count=1)

    plan = ReasoningPlan(
        objective="ship verified work",
        steps=[
            PlanStep(id="plan", title="Plan", instructions="make plan"),
            PlanStep(id="execute", title="Execute", instructions="do work", dependencies=["plan"]),
            PlanStep(id="review", title="Review", instructions="verify", dependencies=["execute"]),
        ],
    )
    result = IntelligenceRuntime(executor).run(plan)

    assert result["ok"] is True
    assert result["succeeded"] == ["plan", "execute", "review"]
    assert observed == [("plan", []), ("execute", ["plan"]), ("review", ["execute", "plan"])]
    assert all(step.status == StepStatus.SUCCEEDED for step in plan.steps)


def test_runtime_retries_when_reviewer_requests_more_evidence():
    calls = {"count": 0}

    def executor(step, completed):
        calls["count"] += 1
        if calls["count"] == 1:
            return StepResult(ok=True)
        return StepResult(ok=True, evidence=[{"verified": True}])

    plan = ReasoningPlan(
        objective="produce evidence",
        steps=[PlanStep(id="verify", title="Verify", instructions="verify", retry_policy=RetryPolicy(max_attempts=2))],
    )
    result = IntelligenceRuntime(executor).run(plan)

    assert result["ok"] is True
    assert calls["count"] == 2
    assert plan.steps[0].attempts == 2
    assert plan.steps[0].review.verdict == ReviewVerdict.PASS


def test_runtime_blocks_dependents_after_failure():
    def executor(step, completed):
        if step.id == "build":
            return StepResult(ok=False, error="permanent compilation failure")
        return StepResult(ok=True, evidence=[{"unexpected": True}])

    plan = ReasoningPlan(
        objective="build then package",
        steps=[
            PlanStep(id="build", title="Build", instructions="build", retry_policy=RetryPolicy(max_attempts=1)),
            PlanStep(id="package", title="Package", instructions="package", dependencies=["build"]),
        ],
    )
    result = IntelligenceRuntime(executor).run(plan)

    assert result["ok"] is False
    assert result["failed"] == ["build"]
    assert result["blocked"] == ["package"]
    assert plan.steps[1].status == StepStatus.BLOCKED


def test_runtime_supports_independent_reviewer_policy():
    def executor(step, completed):
        return StepResult(ok=True, evidence=[{"value": 1}])

    def reviewer(step, result):
        return ReviewResult(ReviewVerdict.FAIL, "policy rejected output", confidence=0.99)

    plan = ReasoningPlan(objective="reviewed task", steps=[PlanStep(id="x", title="X", instructions="x")])
    result = IntelligenceRuntime(executor, reviewer).run(plan)

    assert result["ok"] is False
    assert result["failed"] == ["x"]
    assert plan.steps[0].review.reason == "policy rejected output"


def test_from_normalized_plan_maps_integer_dependencies():
    normalized = {
        "summary": "test normalized plan",
        "contract": {"objective": "objective from contract"},
        "steps": [
            {"title": "One", "instructions": "first", "dependencies": [], "max_attempts": 2},
            {"title": "Two", "instructions": "second", "dependencies": [0], "max_attempts": 3},
        ],
        "success_criteria": ["done"],
    }
    plan = IntelligenceRuntime.from_normalized_plan(normalized)

    assert plan.objective == "objective from contract"
    assert plan.steps[0].id == "step-1"
    assert plan.steps[1].dependencies == ["step-1"]
    assert plan.steps[1].retry_policy.max_attempts == 3
