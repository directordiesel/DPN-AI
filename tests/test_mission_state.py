from app.intelligence_runtime import PlanStep, ReasoningPlan, ReviewResult, ReviewVerdict, StepResult, StepStatus
from app.mission_state import MissionState, MissionStatus


def test_mission_state_tracks_success_metrics_and_files():
    plan = ReasoningPlan(
        objective="ship verified output",
        steps=[PlanStep(id="one", title="One", instructions="x"), PlanStep(id="two", title="Two", instructions="y")],
    )
    plan.steps[0].status = StepStatus.SUCCEEDED
    plan.steps[0].attempts = 1
    plan.steps[0].result = StepResult(ok=True, tool_count=2, generated_files=["generated/a.txt"])
    plan.steps[0].review = ReviewResult(ReviewVerdict.PASS, "ok", 0.9)
    plan.steps[1].status = StepStatus.SUCCEEDED
    plan.steps[1].attempts = 2
    plan.steps[1].result = StepResult(ok=True, tool_count=1, generated_files=["generated/a.txt", "generated/b.txt"])
    plan.steps[1].review = ReviewResult(ReviewVerdict.PASS, "ok", 1.0)

    state = MissionState.from_plan("mission-1", plan).refresh(plan)
    summary = state.summary()

    assert state.status == MissionStatus.SUCCEEDED
    assert state.total_attempts == 3
    assert state.tool_calls == 3
    assert state.generated_files == ["generated/a.txt", "generated/b.txt"]
    assert summary["progress"]["completed"] == 2
    assert summary["reviewer_confidence"] == 0.95


def test_mission_state_reports_partial_when_some_work_succeeds_then_fails():
    plan = ReasoningPlan(
        objective="partial mission",
        steps=[PlanStep(id="one", title="One", instructions="x"), PlanStep(id="two", title="Two", instructions="y")],
    )
    plan.steps[0].status = StepStatus.SUCCEEDED
    plan.steps[0].result = StepResult(ok=True)
    plan.steps[1].status = StepStatus.FAILED
    plan.steps[1].result = StepResult(ok=False, error="boom")

    state = MissionState.from_plan("mission-2", plan).refresh(plan)

    assert state.status == MissionStatus.PARTIAL
    assert state.completed_step_ids == ["one"]
    assert state.failed_step_ids == ["two"]


def test_mission_state_rejects_blank_identifier():
    plan = ReasoningPlan(objective="x", steps=[PlanStep(id="one", title="One", instructions="x")])
    try:
        MissionState.from_plan(" ", plan)
    except ValueError as exc:
        assert "mission_id" in str(exc)
    else:
        raise AssertionError("blank mission id was accepted")
