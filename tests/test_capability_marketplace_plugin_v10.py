from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.capability_forge import CapabilityForge
from plugins.capability_marketplace_v10 import register


class FakeRegistry:
    def __init__(self, root: Path) -> None:
        self.settings = SimpleNamespace(data_dir=root / "data")
        self.forge = CapabilityForge(root / "plugins", root / "data")
        self.tools = {}

    def register(self, name, description, parameters, function, gate=None, risk="read"):
        self.tools[name] = {"description": description, "parameters": parameters, "function": function, "gate": gate, "risk": risk}


def test_marketplace_plugin_preserves_high_risk_activation_boundary(tmp_path):
    registry = FakeRegistry(tmp_path)
    register(registry)

    assert hasattr(registry, "capability_marketplace_v10")
    assert registry.tools["list_marketplace_packages_v10"]["risk"] == "read"
    assert registry.tools["inspect_marketplace_package_v10"]["risk"] == "read"
    assert registry.tools["stage_marketplace_package_v10"]["risk"] == "write"
    assert registry.tools["validate_marketplace_package_v10"]["risk"] == "read"

    promote = registry.tools["promote_marketplace_package_v10"]
    rollback = registry.tools["rollback_marketplace_package_v10"]
    assert promote["risk"] == "destructive"
    assert promote["gate"] == "commands"
    assert rollback["risk"] == "destructive"
    assert rollback["gate"] == "commands"
