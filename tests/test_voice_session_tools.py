from pathlib import Path
from types import SimpleNamespace

from app.tools.voice_session import install_voice_session_tools


class RegistryStub:
    def __init__(self, workspace: Path):
        self.settings = SimpleNamespace(workspace_dir=workspace)
        self.registered: dict[str, dict] = {}

    def register(self, name, description, parameters, function, gate=None, risk="read"):
        self.registered[name] = {
            "description": description,
            "parameters": parameters,
            "function": function,
            "gate": gate,
            "risk": risk,
        }


def test_installer_ignores_minimal_plugin_loader_stub():
    stub = SimpleNamespace(registered=False)
    assert install_voice_session_tools(stub) is None
    assert not hasattr(stub, "voice_session_runtime")


def test_installer_registers_voice_session_tools(tmp_path: Path):
    registry = RegistryStub(tmp_path)
    runtime = install_voice_session_tools(registry)
    assert runtime is not None
    assert registry.voice_session_runtime is runtime
    expected = {
        "voice_session_status",
        "start_voice_session",
        "stop_voice_session",
        "begin_voice_turn",
        "voice_begin_speaking",
        "interrupt_voice",
        "complete_voice_turn",
    }
    assert expected.issubset(registry.registered)
    assert registry.registered["start_voice_session"]["gate"] == "voice"
    assert registry.registered["interrupt_voice"]["risk"] == "execute"


def test_registered_begin_turn_tracks_attachment_modalities(tmp_path: Path):
    image = tmp_path / "screen.png"
    image.write_bytes(b"image")
    registry = RegistryStub(tmp_path)
    install_voice_session_tools(registry)
    begin_turn = registry.registered["begin_voice_turn"]["function"]
    result = begin_turn(
        "Inspect this screen",
        attachments=[{"path": "screen.png", "media_type": "image"}],
        source="voice",
    )
    assert result["ok"] is True
    assert result["turn"]["modalities"] == ["image", "text"]
