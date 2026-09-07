from __future__ import annotations

import asyncio
import json

import pytest

from app.specialist_execution_v10 import SpecialistExecutionError, SpecialistExecutionFacade
from app.specialist_organization_v10 import SpecialistOrganization


def _catalog():
    return [
        {"name": "read_file", "risk": "read", "gate": None},
        {"name": "external_write", "risk": "external", "gate": "connectors"},
    ]


def _organization(tmp_path, mission_lookup=None):
    return SpecialistOrganization(
        tmp_path / "specialists.json",
        tool_catalog=_catalog,
        mission_lookup=mission_lookup,
    )


def _register_enabled(org, specialist_id="s-1", allowed=None):
    org.register_specialist(
        specialist_id=specialist_id,
        name=f"Specialist {specialist_id}",
        role="Verification specialist",
        capability_tags=["verification"],
        allowed_tools=allowed or ["read_file", "external_write"],
    )
    org.set_specialist_enabled(specialist_id, True)


def test_release_specialist_persistence_recovery(tmp_path):
    org = _organization(tmp_path)
    _register_enabled(org)
    org.assign(
        assignment_id="a-1",
        specialist_id="s-1",
        objective="Persist this assignment",
        required_tools=["read_file"],
    )

    recovered = _organization(tmp_path)
    context = recovered.assignment_context("a-1")
    assert context["assignment"]["status"] == "active"
    assert context["specialist"]["enabled"] is True
    assert context["execution_authorized"] is False
    assert [item["name"] for item in context["allowed_tool_catalog"]] == ["read_file", "external_write"]


def test_release_specialist_capability_isolation(tmp_path):
    org = _organization(tmp_path)
    _register_enabled(org, allowed=["read_file"])
    org.assign(
        assignment_id="a-1",
        specialist_id="s-1",
        objective="Read only",
        required_tools=["read_file"],
    )
    calls = []

    async def execute(*args):
        calls.append(args)
        return {"ok": True}

    facade = SpecialistExecutionFacade(resolve_assignment=org.assignment_context, execute_tool=execute)
    with pytest.raises(SpecialistExecutionError, match="outside specialist capability"):
        asyncio.run(
            facade.execute(
                assignment_id="a-1",
                tool_name="external_write",
                arguments={"value": "blocked"},
                permissions={"allow_connectors": True},
            )
        )
    assert calls == []


def test_release_specialist_handoff_integrity(tmp_path):
    org = _organization(tmp_path)
    _register_enabled(org, "s-1", ["read_file"])
    _register_enabled(org, "s-2", ["read_file"])
    org.assign(
        assignment_id="a-1",
        specialist_id="s-1",
        objective="Handoff safely",
        required_tools=["read_file"],
    )
    raw_context = {"secret_context": "do-not-persist-raw"}
    assignment, receipt = org.handoff(
        assignment_id="a-1",
        to_specialist_id="s-2",
        reason="specialist transition",
        context=raw_context,
    )
    persisted = (tmp_path / "specialists.json").read_text(encoding="utf-8")
    assert assignment.specialist_id == "s-2"
    assert assignment.handoff_count == 1
    assert len(receipt.context_digest) == 64
    assert "do-not-persist-raw" not in persisted
    assert receipt.context_digest in persisted


def test_release_specialist_mission_integration(tmp_path):
    mission = {"mission_id": "m-1", "status": "active"}
    lookup = lambda mission_id: mission if mission_id == "m-1" else None
    org = _organization(tmp_path, lookup)
    _register_enabled(org, allowed=["read_file"])
    org.assign(
        assignment_id="a-1",
        specialist_id="s-1",
        objective="Operate inside an existing mission",
        mission_id="m-1",
        required_tools=["read_file"],
    )
    calls = []

    async def execute(name, arguments, permissions):
        calls.append((name, arguments, permissions))
        return {"ok": True, "path": arguments["path"]}

    facade = SpecialistExecutionFacade(
        resolve_assignment=org.assignment_context,
        execute_tool=execute,
        mission_lookup=lookup,
    )
    receipt = asyncio.run(
        facade.execute(
            assignment_id="a-1",
            tool_name="read_file",
            arguments={"path": "README.md"},
            permissions={"approval_mode": "standard", "run_id": "run-1"},
        )
    )
    assert receipt.ok is True
    assert receipt.mission_id == "m-1"
    assert calls[0][0] == "read_file"


def test_release_specialist_approval_boundary(tmp_path):
    org = _organization(tmp_path)
    _register_enabled(org)
    org.assign(
        assignment_id="a-1",
        specialist_id="s-1",
        objective="Request governed external work",
        required_tools=["external_write"],
    )

    async def execute(name, arguments, permissions):
        assert name == "external_write"
        return {
            "ok": False,
            "approval_required": True,
            "approval_id": "approval-1",
            "error": "approval required",
        }

    facade = SpecialistExecutionFacade(resolve_assignment=org.assignment_context, execute_tool=execute)
    receipt = asyncio.run(
        facade.execute(
            assignment_id="a-1",
            tool_name="external_write",
            arguments={"payload": "bounded"},
            permissions={"allow_connectors": True, "approval_mode": "standard"},
        )
    )
    assert receipt.ok is False
    assert receipt.approval_pending is True
    assert receipt.result["approval_id"] == "approval-1"
    assert receipt.execution_authorized_by_specialist is False
