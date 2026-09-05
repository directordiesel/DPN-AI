from pathlib import Path
from types import SimpleNamespace

from app.plugins import load_plugins


class RegistryStub:
    def __init__(self, workspace: Path):
        self.settings = SimpleNamespace(workspace_dir=workspace)
        self.images = SimpleNamespace(generate=None)
        self.registered: dict[str, dict] = {}

    def register(self, name, description, parameters, function, gate=None, risk="read"):
        self.registered[name] = {
            "description": description,
            "parameters": parameters,
            "function": function,
            "gate": gate,
            "risk": risk,
        }


def test_core_plugin_loader_installs_voice_session_tools(tmp_path: Path):
    registry = RegistryStub(tmp_path)
    errors = load_plugins(tmp_path / "plugins", registry)
    assert errors == []
    assert "voice_session_status" in registry.registered
    assert "begin_voice_turn" in registry.registered
    assert hasattr(registry, "voice_session_runtime")
