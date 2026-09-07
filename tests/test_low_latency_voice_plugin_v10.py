from __future__ import annotations

from types import SimpleNamespace

from app.voice_session_v9 import VoiceSessionRuntime
from plugins.low_latency_voice_v10 import register


class StubRegistry:
    def __init__(self, tmp_path, voice):
        self.voice = voice
        self.voice_session_runtime = VoiceSessionRuntime(tmp_path)
        self.registered: dict[str, dict] = {}

    def register(self, name, description, parameters, function, gate=None, risk="read"):
        self.registered[name] = {
            "description": description,
            "parameters": parameters,
            "function": function,
            "gate": gate,
            "risk": risk,
        }


def test_low_latency_voice_plugin_reuses_existing_voice_and_session(tmp_path):
    voice = SimpleNamespace()
    registry = StubRegistry(tmp_path, voice)

    register(registry)

    runtime = registry.low_latency_voice_runtime_v10
    assert runtime.adapter is voice
    assert runtime.session_runtime is registry.voice_session_runtime
    assert set(registry.registered) == {
        "voice_v10_status",
        "voice_v10_synthesize_active_turn",
        "voice_v10_transcribe_audio",
        "voice_v10_interrupt",
    }
    assert registry.registered["voice_v10_status"]["gate"] == "voice"
    assert registry.registered["voice_v10_status"]["risk"] == "read"
    assert registry.registered["voice_v10_synthesize_active_turn"]["gate"] == "voice"
    assert registry.registered["voice_v10_synthesize_active_turn"]["risk"] == "execute"
    assert registry.registered["voice_v10_transcribe_audio"]["risk"] == "execute"
    assert registry.registered["voice_v10_interrupt"]["risk"] == "execute"


def test_low_latency_voice_plugin_fails_closed_when_shared_dependencies_are_missing(tmp_path):
    class IncompleteRegistry:
        def __init__(self):
            self.registered = {}

        def register(self, *args, **kwargs):
            self.registered[args[0] if args else kwargs["name"]] = kwargs

    registry = IncompleteRegistry()
    register(registry)

    assert registry.registered == {}
    assert not hasattr(registry, "low_latency_voice_runtime_v10")
