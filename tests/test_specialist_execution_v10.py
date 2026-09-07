from __future__ import annotations

import asyncio

import pytest

from app.specialist_execution_v10 import SpecialistExecutionError, SpecialistExecutionFacade


def _context(*, status="active", enabled=True, mission_id="", allowed=None, required=None):
    allowed = allowed or [
        {"name": "read_file", "risk": "read", "gate": None},
        {"name": "external_write", "risk": "external", "gate": "connectors"},
    ]
    return {
        "assignment": {
            "assignment_id": "a-1",
            "specialist_id": "s-1",
            "objective": "Perform bounded specialist work",
            "mission_id": mission_id,
            "required_tools": required or ["read_file"],
            "status": status,
        },
        "specialist": {
            "specialist_id": "s-1",
            "enabled": enabled,
            "allowed_tools": [item["name"] for item in allowed],
        },
        "allowed_tool_catalog": allowed,
        "execution_authorized": False,
    }


def test_specialist_execution_delegates_allowed_tool_with_host_permissions():
    calls = []

    async def execute(name, arguments, permissions):
        calls.append((name, arguments, permissions))
        return {"ok": True, "value": "verified"}

    facade = SpecialistExecutionFacade(resolve_assignment=lambda _: _context(), execute_tool=execute)
    permissions = {"allow_web": False, "approval_mode": "standard", "run_id": "run-1"}
    receipt = asyncio.run(
        facade.execute(
            assignment_id="a-1",
            tool_name="read_file",
            arguments={"path": "README.md"},
            permissions=permissions,
        )
    )

    assert receipt.ok is True
    assert receipt.execution_authorized_by_specialist is False
    assert calls == [("read_file", {"path": "README.md"}, permissions)]


def test_specialist_execution_blocks_tool_outside_live_allowlist_before_registry_call():
    calls = []

    async def execute(*args):
        calls.append(args)
        return {"ok": True}

    facade = SpecialistExecutionFacade(resolve_assignment=lambda _: _context(), execute_tool=execute)
    with pytest.raises(SpecialistExecutionError, match="outside specialist capability"):
        asyncio.run(
            facade.execute(
                assignment_id="a-1",
                tool_name="delete_path",
                arguments={"path": "x"},
                permissions={"approval_mode": "standard"},
            )
        )
    assert calls == []


def test_specialist_execution_preserves_toolregistry_approval_pending_result():
    async def execute(name, arguments, permissions):
        assert name == "external_write"
        assert permissions["allow_connectors"] is True
        return {
            "ok": False,
            "approval_required": True,
            "approval_id": "approval-123",
            "error": "approval required",
        }

    facade = SpecialistExecutionFacade(resolve_assignment=lambda _: _context(), execute_tool=execute)
    receipt = asyncio.run(
        facade.execute(
            assignment_id="a-1",
            tool_name="external_write",
            arguments={"value": "bounded"},
            permissions={"allow_connectors": True, "approval_mode": "standard"},
        )
    )
    assert receipt.ok is False
    assert receipt.approval_pending is True
    assert receipt.result["approval_id"] == "approval-123"
    assert receipt.execution_authorized_by_specialist is False


def test_specialist_execution_rejects_terminal_assignment():
    facade = SpecialistExecutionFacade(
        resolve_assignment=lambda _: _context(status="completed"),
        execute_tool=lambda *args: None,
    )
    with pytest.raises(SpecialistExecutionError, match="not active"):
        asyncio.run(
            facade.execute(
                assignment_id="a-1", tool_name="read_file", arguments={}, permissions={}
            )
        )


def test_specialist_execution_rejects_non_authorizing_context_drift():
    context = _context()
    context["execution_authorized"] = True
    facade = SpecialistExecutionFacade(resolve_assignment=lambda _: context, execute_tool=lambda *args: None)
    with pytest.raises(SpecialistExecutionError, match="must remain non-authorizing"):
        asyncio.run(
            facade.execute(
                assignment_id="a-1", tool_name="read_file", arguments={}, permissions={}
            )
        )


def test_specialist_execution_verifies_bound_mission_still_exists_and_is_nonterminal():
    calls = []

    async def execute(*args):
        calls.append(args)
        return {"ok": True}

    missing = SpecialistExecutionFacade(
        resolve_assignment=lambda _: _context(mission_id="m-1"),
        execute_tool=execute,
        mission_lookup=lambda _: None,
    )
    with pytest.raises(SpecialistExecutionError, match="no longer exists"):
        asyncio.run(missing.execute(assignment_id="a-1", tool_name="read_file", arguments={}, permissions={}))

    terminal = SpecialistExecutionFacade(
        resolve_assignment=lambda _: _context(mission_id="m-1"),
        execute_tool=execute,
        mission_lookup=lambda _: {"mission_id": "m-1", "status": "completed"},
    )
    with pytest.raises(SpecialistExecutionError, match="mission is terminal"):
        asyncio.run(terminal.execute(assignment_id="a-1", tool_name="read_file", arguments={}, permissions={}))
    assert calls == []


def test_specialist_execution_rejects_required_tool_boundary_drift():
    facade = SpecialistExecutionFacade(
        resolve_assignment=lambda _: _context(required=["read_file", "missing_tool"]),
        execute_tool=lambda *args: None,
    )
    with pytest.raises(SpecialistExecutionError, match="capability boundary drift"):
        asyncio.run(facade.execute(assignment_id="a-1", tool_name="read_file", arguments={}, permissions={}))
