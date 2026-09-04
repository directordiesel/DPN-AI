from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "agent_runtime_v7.py"
spec = importlib.util.spec_from_file_location("agent_runtime_v7", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_agent_mission_is_bounded_and_verification_driven():
    mission = module.build_agent_mission(
        "Improve repository safely",
        acceptance_criteria=["tests pass", "security remains enforced"],
        requested_capabilities=["coding", "verification"],
        max_steps=99,
        max_repair_passes=99,
    )
    assert mission["ok"] is True
    assert mission["step_budget"] == 32
    assert mission["repair_budget"] == 5
    assert mission["execution_policy"]["completion_requires_verification"] is True
    assert mission["execution_policy"]["approval_boundaries_preserved"] is True
    assert mission["execution_policy"]["workspace_confinement_preserved"] is True
    assert mission["execution_policy"]["bounded_repairs"] is True
    names = [stage["name"] for stage in mission["stages"]]
    assert names[:3] == ["understand", "inspect_context", "plan"]
    assert "verify" in names
    assert "repair" in names
    assert names[-1] == "checkpoint"


def test_agent_mission_rejects_empty_objective():
    result = module.build_agent_mission("   ")
    assert result["ok"] is False
    assert result["error"] == "objective is required"


def test_agent_role_router_prefers_specialists():
    assert module.route_agent_role("fix repository bug")["role"] == "coder"
    assert module.route_agent_role("create an image artifact")["role"] == "creator"
    assert module.route_agent_role("schedule a recurring workflow")["role"] == "automation"
    assert module.route_agent_role("research current sources")["role"] == "researcher"
    assert module.route_agent_role("run security audit")["role"] == "verifier"
    assert module.route_agent_role("think through the objective")["role"] == "planner"


def test_completed_step_requires_evidence():
    blocked = module.evaluate_agent_step("complete", evidence=[])
    assert blocked["state"] == "blocked"
    assert blocked["reason"] == "completion_requires_evidence"

    complete = module.evaluate_agent_step("complete", evidence=["pytest: 18 passed"])
    assert complete["state"] == "complete"
    assert complete["reason"] is None


def test_approval_boundary_blocks_execution_and_completion():
    for state in ("ready", "running", "complete"):
        result = module.evaluate_agent_step(
            state,
            evidence=["verified"] if state == "complete" else [],
            approval_required=True,
            approval_granted=False,
        )
        assert result["state"] == "blocked"
        assert result["reason"] == "approval_required"


def test_granted_approval_does_not_bypass_evidence_gate():
    result = module.evaluate_agent_step(
        "complete",
        evidence=[],
        approval_required=True,
        approval_granted=True,
    )
    assert result["state"] == "blocked"
    assert result["reason"] == "completion_requires_evidence"


def test_invalid_state_falls_back_to_pending():
    result = module.evaluate_agent_step("magic")
    assert result["requested_state"] == "pending"
    assert result["state"] == "pending"
