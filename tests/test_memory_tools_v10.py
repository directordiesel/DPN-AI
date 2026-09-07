from __future__ import annotations

from app.memory_scope import MemoryScope
from app.permission_engine import PermissionEngine, PermissionMode
from app.tool_permission_runtime import ToolPermissionRuntime
from app.memory_tool_service_v10 import GovernedMemoryToolService
from plugins import layered_memory_v10


class FakeRegistry:
    def __init__(self, *, authorizer=None):
        self.db = object()
        self.semantic = object()
        self.tools = {}
        if authorizer is not None:
            self.memory_scope_authorizer = authorizer

    def register(self, *, name, description, parameters, function, gate=None, risk="read"):
        self.tools[name] = {
            "description": description,
            "parameters": parameters,
            "function": function,
            "gate": gate,
            "risk": risk,
        }


def test_plugin_registers_only_bounded_memory_surface():
    registry = FakeRegistry()
    layered_memory_v10.register(registry)
    assert set(registry.tools) == {
        "dpn_memory_recall",
        "dpn_memory_remember",
        "dpn_memory_lineage_inspect",
        "dpn_memory_supersede",
    }
    assert registry.tools["dpn_memory_recall"]["risk"] == "read"
    assert registry.tools["dpn_memory_lineage_inspect"]["risk"] == "read"
    assert registry.tools["dpn_memory_remember"]["risk"] == "execute"
    assert registry.tools["dpn_memory_supersede"]["risk"] == "destructive"
    for tool in registry.tools.values():
        properties = tool["parameters"].get("properties", {})
        assert "approval_granted" not in properties
        assert "sensitive" not in properties
        assert "sql" not in properties
        assert "delete" not in properties


def test_supersession_forces_human_approval_even_when_policy_allows():
    engine = PermissionEngine(PermissionMode.ALWAYS_ALLOW)
    runtime = ToolPermissionRuntime(engine)
    authorization = runtime.authorize(
        tool_name="dpn_memory_supersede",
        declared_risk="destructive",
        gate=None,
        permissions={"approval_mode": "autonomous"},
        use_v9_policy=True,
        arguments={"key": "release_target"},
    )
    assert authorization.allowed is False
    assert authorization.approval_required is True
    assert authorization.decision.source == "memory_supersession_boundary"
    assert "requires explicit human approval" in authorization.reason


def test_non_global_scope_fails_closed_without_host_authorizer():
    service = GovernedMemoryToolService(object(), object())
    result = service.inspect_lineage(scope="project", project_id="p1")
    assert result["ok"] is False
    assert result["report"] is None
    assert "trusted host authorization" in result["error"]


def test_lineage_inspection_rejects_scope_without_required_identity_even_when_authorized():
    service = GovernedMemoryToolService(object(), object(), scope_authorizer=lambda scope, context: True)
    result = service.inspect_lineage(scope="project")
    assert result["ok"] is False
    assert result["report"] is None
    assert "project_id" in result["error"]


def test_host_authorizer_receives_scope_and_context_before_non_global_access():
    seen = []

    def authorize(scope, context):
        seen.append((scope, context.project_id, context.user_id))
        return scope == MemoryScope.PROJECT and context.project_id == "p1" and context.user_id is None

    service = GovernedMemoryToolService(object(), object(), scope_authorizer=authorize)
    result = service.inspect_lineage(scope="project", project_id="p1")
    # Storage is a stub and will fail after authorization; the important boundary is
    # that host authorization happened first with the exact requested context.
    assert seen == [(MemoryScope.PROJECT, "p1", None)]
    assert result["ok"] is False
    assert "durable memory could not be inspected" in result["error"]


def test_tool_schema_requires_evidence_for_supersession_and_has_no_working_target():
    registry = FakeRegistry()
    layered_memory_v10.register(registry)
    schema = registry.tools["dpn_memory_supersede"]["parameters"]
    required = set(schema["required"])
    assert {"evidence_ids", "supersedes_memory_ids", "reason"}.issubset(required)
    assert "working" not in schema["properties"]["layer"]["enum"]
