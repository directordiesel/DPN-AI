from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from plugins.specialist_organization_v10 import register


class FakeDB:
    def get_mission(self, mission_id):
        if mission_id == "mission-1":
            return {"id": mission_id, "status": "running"}
        return None


class FakeRegistry:
    def __init__(self, tmp_path: Path):
        self.settings = SimpleNamespace(data_dir=tmp_path)
        self.db = FakeDB()
        self.registered = {}
        self._catalog = [
            {"name": "read_file", "risk": "read", "gate": None, "description": "read"},
            {"name": "search_web", "risk": "external", "gate": "network", "description": "search"},
        ]

    def catalog(self):
        return [*self._catalog, *[
            {"name": name, "risk": item["risk"], "gate": item.get("gate"), "description": item["description"]}
            for name, item in self.registered.items()
        ]]

    def register(self, *, name, description, parameters, function, gate=None, risk="read"):
        self.registered[name] = {
            "description": description,
            "parameters": parameters,
            "function": function,
            "gate": gate,
            "risk": risk,
        }


def test_plugin_registers_persistent_nonexecuting_governed_surface(tmp_path):
    registry = FakeRegistry(tmp_path)
    register(registry)

    assert hasattr(registry, "specialist_organization_v10")
    assert hasattr(registry, "resolve_specialist_assignment_v10")
    assert registry.registered["specialist_organization_v10_status"]["risk"] == "read"
    assert registry.registered["list_specialists_v10"]["risk"] == "read"
    assert registry.registered["register_specialist_v10"]["risk"] == "write"
    assert registry.registered["assign_specialist_v10"]["risk"] == "write"
    assert registry.registered["handoff_specialist_assignment_v10"]["risk"] == "write"
    assert "execute_specialist_v10" not in registry.registered


def test_plugin_flow_binds_mission_and_never_authorizes_execution(tmp_path):
    registry = FakeRegistry(tmp_path)
    register(registry)

    create = registry.registered["register_specialist_v10"]["function"]
    enable = registry.registered["set_specialist_enabled_v10"]["function"]
    assign = registry.registered["assign_specialist_v10"]["function"]
    inspect = registry.registered["inspect_specialist_assignment_context_v10"]["function"]

    created = create("researcher", "Research Specialist", "research", allowed_tools=["read_file", "search_web"])
    assert created["enabled"] is False
    assert created["execution_performed"] is False
    enabled = enable("researcher", True)
    assert enabled["specialist"]["enabled"] is True
    assigned = assign("a1", "researcher", "Research mission", "mission-1", ["search_web"])
    assert assigned["assignment"]["mission_id"] == "mission-1"
    assert assigned["execution_performed"] is False
    context = inspect("a1")
    assert context["execution_authorized"] is False
    assert {item["name"] for item in context["allowed_tool_catalog"]} == {"read_file", "search_web"}


def test_plugin_handoff_records_digest_without_storing_raw_context(tmp_path):
    registry = FakeRegistry(tmp_path)
    register(registry)
    create = registry.registered["register_specialist_v10"]["function"]
    enable = registry.registered["set_specialist_enabled_v10"]["function"]
    assign = registry.registered["assign_specialist_v10"]["function"]
    handoff = registry.registered["handoff_specialist_assignment_v10"]["function"]

    for sid in ("researcher", "reviewer"):
        create(sid, sid.title(), "research", allowed_tools=["read_file"])
        enable(sid, True)
    assign("a1", "researcher", "Review evidence", "mission-1", ["read_file"])
    result = handoff("a1", "reviewer", "Independent verification", {"secret_context": "do-not-persist-raw"})

    assert result["execution_performed"] is False
    assert len(result["handoff"]["context_digest"]) == 64
    state_text = (tmp_path / "specialist_organization_v10.json").read_text(encoding="utf-8")
    assert "do-not-persist-raw" not in state_text
