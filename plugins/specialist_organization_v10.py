from __future__ import annotations

from app.specialist_organization_v10 import SpecialistOrganization


def register(registry):
    organization = SpecialistOrganization(
        registry.settings.data_dir / "specialist_organization_v10.json",
        tool_catalog=registry.catalog,
        mission_lookup=registry.db.get_mission,
    )
    registry.specialist_organization_v10 = organization

    # Host-side runtimes may request a validated assignment context. The returned
    # context is capability-scoped metadata only and never authorizes execution.
    registry.resolve_specialist_assignment_v10 = organization.assignment_context

    registry.register(
        name="specialist_organization_v10_status",
        description="Inspect persistent v10 specialist organization counts and safety state without invoking any specialist or tool.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        function=organization.status,
        risk="read",
    )

    registry.register(
        name="list_specialists_v10",
        description="List persistent specialist identities, roles, capability tags, allowed-tool boundaries, and enabled state.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        function=lambda: {"ok": True, "specialists": [item.to_dict() for item in organization.list_specialists()]},
        risk="read",
    )

    registry.register(
        name="list_specialist_assignments_v10",
        description="List persistent specialist assignments, optionally limited to one existing mission. This does not start or resume mission work.",
        parameters={
            "type": "object",
            "properties": {"mission_id": {"type": ["string", "null"], "default": None, "maxLength": 160}},
            "additionalProperties": False,
        },
        function=lambda mission_id=None: {"ok": True, "assignments": [item.to_dict() for item in organization.list_assignments(mission_id=mission_id)]},
        risk="read",
    )

    registry.register(
        name="register_specialist_v10",
        description="Persist a bounded specialist identity and capability boundary. New specialists are always disabled and cannot execute work.",
        parameters={
            "type": "object",
            "properties": {
                "specialist_id": {"type": "string", "minLength": 1, "maxLength": 80},
                "name": {"type": "string", "minLength": 1, "maxLength": 120},
                "role": {"type": "string", "minLength": 1, "maxLength": 120},
                "description": {"type": "string", "maxLength": 1000, "default": ""},
                "capability_tags": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 120}, "maxItems": 32, "default": []},
                "allowed_tools": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 120}, "maxItems": 64, "default": []},
            },
            "required": ["specialist_id", "name", "role"],
            "additionalProperties": False,
        },
        function=lambda specialist_id, name, role, description="", capability_tags=None, allowed_tools=None: {
            "ok": True,
            "specialist": organization.register_specialist(
                specialist_id=specialist_id,
                name=name,
                role=role,
                description=description,
                capability_tags=capability_tags or [],
                allowed_tools=allowed_tools or [],
            ).to_dict(),
            "enabled": False,
            "execution_performed": False,
        },
        risk="write",
    )

    registry.register(
        name="set_specialist_enabled_v10",
        description="Enable or disable a persisted specialist identity. This changes organization state only and does not invoke the specialist.",
        parameters={
            "type": "object",
            "properties": {
                "specialist_id": {"type": "string", "minLength": 1, "maxLength": 80},
                "enabled": {"type": "boolean"},
            },
            "required": ["specialist_id", "enabled"],
            "additionalProperties": False,
        },
        function=lambda specialist_id, enabled: {
            "ok": True,
            "specialist": organization.set_specialist_enabled(specialist_id, enabled).to_dict(),
            "execution_performed": False,
        },
        risk="write",
    )

    registry.register(
        name="assign_specialist_v10",
        description="Create a durable specialist assignment after validating enabled identity, live tool capability coverage, and optional existing mission binding. No mission step or tool is executed.",
        parameters={
            "type": "object",
            "properties": {
                "assignment_id": {"type": "string", "minLength": 1, "maxLength": 100},
                "specialist_id": {"type": "string", "minLength": 1, "maxLength": 80},
                "objective": {"type": "string", "minLength": 1, "maxLength": 4000},
                "mission_id": {"type": "string", "maxLength": 160, "default": ""},
                "required_tools": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 120}, "maxItems": 64, "default": []},
            },
            "required": ["assignment_id", "specialist_id", "objective"],
            "additionalProperties": False,
        },
        function=lambda assignment_id, specialist_id, objective, mission_id="", required_tools=None: {
            "ok": True,
            "assignment": organization.assign(
                assignment_id=assignment_id,
                specialist_id=specialist_id,
                objective=objective,
                mission_id=mission_id,
                required_tools=required_tools or [],
            ).to_dict(),
            "execution_performed": False,
        },
        risk="write",
    )

    registry.register(
        name="handoff_specialist_assignment_v10",
        description="Record a bounded non-destructive assignment handoff to another enabled specialist whose capability boundary covers the assignment. Context is stored only as a SHA-256 digest; no work is executed.",
        parameters={
            "type": "object",
            "properties": {
                "assignment_id": {"type": "string", "minLength": 1, "maxLength": 100},
                "to_specialist_id": {"type": "string", "minLength": 1, "maxLength": 80},
                "reason": {"type": "string", "minLength": 1, "maxLength": 1000},
                "context": {},
            },
            "required": ["assignment_id", "to_specialist_id", "reason"],
            "additionalProperties": False,
        },
        function=lambda assignment_id, to_specialist_id, reason, context=None: _handoff(
            organization, assignment_id, to_specialist_id, reason, context
        ),
        risk="write",
    )

    registry.register(
        name="set_specialist_assignment_status_v10",
        description="Update the local lifecycle state of one specialist assignment. Terminal assignments cannot be reopened and this tool does not execute mission work.",
        parameters={
            "type": "object",
            "properties": {
                "assignment_id": {"type": "string", "minLength": 1, "maxLength": 100},
                "status": {"type": "string", "enum": ["pending", "active", "handed_off", "completed", "cancelled"]},
            },
            "required": ["assignment_id", "status"],
            "additionalProperties": False,
        },
        function=lambda assignment_id, status: {
            "ok": True,
            "assignment": organization.set_assignment_status(assignment_id, status).to_dict(),
            "execution_performed": False,
        },
        risk="write",
    )

    registry.register(
        name="inspect_specialist_assignment_context_v10",
        description="Resolve one assignment into its enabled specialist and live allowed-tool catalog. The result is explicitly non-authorizing and performs no tool call.",
        parameters={
            "type": "object",
            "properties": {"assignment_id": {"type": "string", "minLength": 1, "maxLength": 100}},
            "required": ["assignment_id"],
            "additionalProperties": False,
        },
        function=organization.assignment_context,
        risk="read",
    )


def _handoff(organization, assignment_id, to_specialist_id, reason, context):
    assignment, receipt = organization.handoff(
        assignment_id=assignment_id,
        to_specialist_id=to_specialist_id,
        reason=reason,
        context=context,
    )
    return {
        "ok": True,
        "assignment": assignment.to_dict(),
        "handoff": receipt.to_dict(),
        "execution_performed": False,
    }
