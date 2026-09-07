from __future__ import annotations

import json

import pytest

from app.specialist_organization_v10 import SpecialistOrganization, SpecialistOrganizationError


def _catalog():
    return [
        {"name": "read_file", "risk": "read", "gate": None, "description": "read"},
        {"name": "search_web", "risk": "external", "gate": "network", "description": "search"},
        {"name": "run_command", "risk": "execute", "gate": "commands", "description": "execute"},
    ]


def _organization(tmp_path, *, missions=None):
    known = missions or {"mission-1": {"id": "mission-1", "status": "running"}}
    return SpecialistOrganization(
        tmp_path / "specialists.json",
        tool_catalog=_catalog,
        mission_lookup=lambda mission_id: known.get(mission_id),
    )


def _register_enabled(org, specialist_id="researcher", tools=("read_file", "search_web")):
    profile = org.register_specialist(
        specialist_id=specialist_id,
        name="Research Specialist",
        role="research",
        description="Evidence-focused specialist",
        capability_tags=("research", "evidence"),
        allowed_tools=tools,
    )
    assert profile.enabled is False
    return org.set_specialist_enabled(specialist_id, True)


def test_specialist_profiles_are_disabled_by_default_and_persist(tmp_path):
    org = _organization(tmp_path)
    profile = org.register_specialist(
        specialist_id="coder",
        name="Coding Specialist",
        role="software",
        allowed_tools=("read_file", "run_command"),
    )
    assert profile.enabled is False

    restarted = _organization(tmp_path)
    restored = restarted.list_specialists()
    assert len(restored) == 1
    assert restored[0].specialist_id == "coder"
    assert restored[0].enabled is False
    assert restarted.status()["execution_authorized"] is False


def test_unknown_tool_is_rejected_before_specialist_persistence(tmp_path):
    org = _organization(tmp_path)
    with pytest.raises(SpecialistOrganizationError, match="unknown tools"):
        org.register_specialist(
            specialist_id="unsafe",
            name="Unsafe",
            role="invalid",
            allowed_tools=("nonexistent_tool",),
        )
    assert org.list_specialists() == []


def test_disabled_specialist_cannot_receive_assignment(tmp_path):
    org = _organization(tmp_path)
    org.register_specialist(specialist_id="researcher", name="Researcher", role="research", allowed_tools=("read_file",))
    with pytest.raises(SpecialistOrganizationError, match="disabled"):
        org.assign(assignment_id="a1", specialist_id="researcher", objective="Inspect evidence")


def test_assignment_binds_existing_mission_and_enforces_tool_coverage(tmp_path):
    org = _organization(tmp_path)
    _register_enabled(org)
    assignment = org.assign(
        assignment_id="a1",
        specialist_id="researcher",
        objective="Research the mission evidence",
        mission_id="mission-1",
        required_tools=("search_web",),
    )
    context = org.assignment_context("a1")
    assert assignment.status == "active"
    assert assignment.mission_id == "mission-1"
    assert context["mission_bound"] is True
    assert context["execution_authorized"] is False
    assert {item["name"] for item in context["allowed_tool_catalog"]} == {"read_file", "search_web"}

    with pytest.raises(SpecialistOrganizationError, match="capability boundary"):
        org.assign(
            assignment_id="a2",
            specialist_id="researcher",
            objective="Execute a command",
            required_tools=("run_command",),
        )


def test_assignment_rejects_unknown_mission(tmp_path):
    org = _organization(tmp_path)
    _register_enabled(org)
    with pytest.raises(SpecialistOrganizationError, match="unknown mission"):
        org.assign(
            assignment_id="a1",
            specialist_id="researcher",
            objective="Work an unknown mission",
            mission_id="missing",
        )


def test_handoff_preserves_assignment_and_records_context_digest(tmp_path):
    org = _organization(tmp_path)
    _register_enabled(org, "researcher", ("read_file", "search_web"))
    _register_enabled(org, "reviewer", ("read_file", "search_web", "run_command"))
    original = org.assign(
        assignment_id="a1", specialist_id="researcher", objective="Validate evidence",
        mission_id="mission-1", required_tools=("read_file", "search_web"),
    )
    updated, receipt = org.handoff(
        assignment_id="a1",
        to_specialist_id="reviewer",
        reason="Independent review required",
        context={"evidence_ids": ["e-1", "e-2"]},
    )
    assert updated.assignment_id == original.assignment_id
    assert updated.specialist_id == "reviewer"
    assert updated.handoff_count == 1
    assert len(receipt.context_digest) == 64
    assert receipt.from_specialist_id == "researcher"
    assert receipt.to_specialist_id == "reviewer"

    restarted = _organization(tmp_path)
    restored = restarted.list_assignments(mission_id="mission-1")[0]
    assert restored.specialist_id == "reviewer"
    assert restored.handoff_count == 1


def test_handoff_rejects_target_without_required_capability(tmp_path):
    org = _organization(tmp_path)
    _register_enabled(org, "researcher", ("read_file", "search_web"))
    _register_enabled(org, "reader", ("read_file",))
    org.assign(
        assignment_id="a1", specialist_id="researcher", objective="Research",
        required_tools=("search_web",),
    )
    with pytest.raises(SpecialistOrganizationError, match="capability boundary"):
        org.handoff(assignment_id="a1", to_specialist_id="reader", reason="Transfer")


def test_terminal_assignment_cannot_be_reopened_or_handed_off(tmp_path):
    org = _organization(tmp_path)
    _register_enabled(org, "researcher", ("read_file",))
    _register_enabled(org, "reviewer", ("read_file",))
    org.assign(assignment_id="a1", specialist_id="researcher", objective="Read", required_tools=("read_file",))
    completed = org.set_assignment_status("a1", "completed")
    assert completed.status == "completed"
    with pytest.raises(SpecialistOrganizationError, match="cannot be reopened"):
        org.set_assignment_status("a1", "active")
    with pytest.raises(SpecialistOrganizationError, match="cannot be handed off"):
        org.handoff(assignment_id="a1", to_specialist_id="reviewer", reason="Late transfer")


def test_corrupt_persistent_state_fails_closed(tmp_path):
    path = tmp_path / "specialists.json"
    path.write_text('{"schema_version":1,"specialists":', encoding="utf-8")
    with pytest.raises(SpecialistOrganizationError, match="unreadable"):
        SpecialistOrganization(path, tool_catalog=_catalog, mission_lookup=lambda _: None)


def test_assignment_context_detects_live_tool_catalog_drift(tmp_path):
    catalog = _catalog()
    org = SpecialistOrganization(
        tmp_path / "specialists.json",
        tool_catalog=lambda: list(catalog),
        mission_lookup=lambda mission_id: {"id": mission_id},
    )
    org.register_specialist(specialist_id="researcher", name="Researcher", role="research", allowed_tools=("search_web",))
    org.set_specialist_enabled("researcher", True)
    org.assign(assignment_id="a1", specialist_id="researcher", objective="Research", required_tools=("search_web",))
    catalog[:] = [item for item in catalog if item["name"] != "search_web"]
    with pytest.raises(SpecialistOrganizationError, match="tool boundary drift"):
        org.assignment_context("a1")


def test_duplicate_specialist_and_assignment_ids_fail_closed(tmp_path):
    org = _organization(tmp_path)
    _register_enabled(org)
    with pytest.raises(SpecialistOrganizationError, match="already exists"):
        org.register_specialist(specialist_id="researcher", name="Duplicate", role="research")
    org.assign(assignment_id="a1", specialist_id="researcher", objective="First")
    with pytest.raises(SpecialistOrganizationError, match="already exists"):
        org.assign(assignment_id="a1", specialist_id="researcher", objective="Second")
