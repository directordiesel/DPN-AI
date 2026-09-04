from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.db import Database
from app.tools.registry import ToolRegistry
from plugins.coding_agent_v6 import build_coding_mission_plan


def test_coding_plan_contains_full_engineering_loop():
    plan = build_coding_mission_plan(
        "Fix the API bug, update the frontend, test everything, and prepare a release",
        project_path="apps/control-center",
        languages=["py", "ts"],
        mode="release",
    )
    names = [phase["name"] for phase in plan["phases"]]
    assert names[:4] == ["inventory", "understand", "snapshot", "implement"]
    assert "static_validation" in names
    assert "test" in names
    assert "repair_loop" in names
    assert "review" in names
    assert "package" in names
    assert names[-1] == "deliver"
    assert plan["languages"] == ["python", "typescript"]
    assert plan["package_release"] is True


def test_coding_plan_bounds_repair_budget_and_normalizes_mode():
    plan = build_coding_mission_plan(
        "repair it",
        languages=["python", "unknown"],
        mode="unsupported",
        max_repair_passes=999,
    )
    assert plan["mode"] == "implement"
    assert plan["max_repair_passes"] == 5
    assert plan["languages"] == ["python"]
    repair = next(phase for phase in plan["phases"] if phase["name"] == "repair_loop")
    assert repair["max_passes"] == 5


def test_coding_plan_requires_evidence_and_preserves_security_boundaries():
    plan = build_coding_mission_plan("Debug the project", mode="debug")
    policy = plan["execution_policy"]
    assert policy["inspect_before_edit"] is True
    assert policy["snapshot_before_broad_changes"] is True
    assert policy["do_not_install_dependencies_implicitly"] is True
    assert policy["do_not_bypass_command_or_approval_gates"] is True
    assert policy["do_not_claim_tests_passed_without_command_evidence"] is True
    assert policy["repair_only_from_observed_failures"] is True


def test_coding_agent_plugin_is_registered_and_selected_by_skill(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        skills_dir=Path(__file__).resolve().parents[1] / "skills",
        plugins_dir=Path(__file__).resolve().parents[1] / "plugins",
        vault_key_path=tmp_path / "data" / "vault.key",
    )
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.database_path)
    registry = ToolRegistry(settings, db)
    assert "plan_coding_mission" in registry.tools
    selected = registry.select_names(
        "debug this application and run its tests",
        profile="software",
        skill_ids=["coding-agent-v6"],
    )
    assert "plan_coding_mission" in selected
    assert "run_command" in selected
    assert "create_workspace_snapshot" in selected
