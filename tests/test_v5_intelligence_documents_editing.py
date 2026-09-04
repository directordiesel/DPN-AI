from __future__ import annotations

import asyncio
from pathlib import Path

from app.agent import DPNAIAgent
from app.artifact_builder import detect_artifact_intent
from app.config import Settings
from app.db import Database
from app.model_gateway import ModelGateway
from app.tools.registry import ToolRegistry


class TextOnlyGateway:
    def __init__(self) -> None:
        self.calls = 0
        self.selected = []

    async def select_best_model(self, requested, **kwargs):
        self.selected.append((requested, kwargs))
        return "qwen3.5:27b"

    async def chat(self, **kwargs):
        self.calls += 1
        return {
            "message": {
                "role": "assistant",
                "content": "# Executive Summary\n\nDPN AI created the requested deliverable.\n\n## Implementation\n\nUse a phased rollout with verification.",
            }
        }


def make_stack(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        static_dir=Path(__file__).resolve().parents[1] / "app" / "static",
        default_model="qwen3.5:9b",
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.database_path)
    tools = ToolRegistry(settings, db)
    return settings, db, tools


def test_artifact_intent_detects_complete_package():
    intent = detect_artifact_intent("Create a complete business package with Word, PDF, Excel, and PowerPoint deliverables")
    assert intent.kinds == ("docx", "pdf", "xlsx", "pptx")


def test_document_fallback_creates_real_file_when_model_does_not_call_tool(tmp_path: Path):
    settings, db, tools = make_stack(tmp_path)
    gateway = TextOnlyGateway()
    result = asyncio.run(
        DPNAIAgent(settings, db, gateway, tools).run(
            conversation_id=None,
            user_message="Create a Word document about a DPN Technology automation rollout",
        )
    )
    assert result.model == "qwen3.5:27b"
    assert result.generated_files
    assert result.generated_files[0].endswith(".docx")
    assert (settings.workspace_dir / result.generated_files[0]).exists()
    assert any(trace.name == "create_word_document" and trace.ok for trace in result.traces)


def test_edit_and_resend_truncates_later_messages(tmp_path: Path):
    settings, db, tools = make_stack(tmp_path)
    gateway = TextOnlyGateway()
    agent = DPNAIAgent(settings, db, gateway, tools)
    first = asyncio.run(agent.run(conversation_id=None, user_message="Tell me about DPN AI"))
    second = asyncio.run(
        agent.run(
            conversation_id=first.conversation_id,
            user_message="Create a better explanation of DPN AI",
            edit_message_id=first.user_message_id,
        )
    )
    messages = db.get_messages(second.conversation_id, limit=20)
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "Create a better explanation of DPN AI"
    assert second.user_message_id != first.user_message_id


def test_model_scoring_prefers_larger_advanced_generative_model():
    small = {"name": "qwen3.5:9b", "size": 6_000_000_000, "details": {"parameter_size": "9B"}}
    large = {"name": "qwen3.5:27b", "size": 18_000_000_000, "details": {"parameter_size": "27B"}}
    embed = {"name": "nomic-embed-text", "size": 300_000_000, "details": {"parameter_size": "0.3B"}}
    assert ModelGateway._model_score(large) > ModelGateway._model_score(small)
    assert ModelGateway._model_score(embed) < 0


def test_ui_exposes_editable_voice_and_maximum_model_controls():
    root = Path(__file__).resolve().parents[1]
    html = (root / "app" / "static" / "index.html").read_text(encoding="utf-8")
    js = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    desktop_js = (root / "app" / "static" / "v8-desktop.js").read_text(encoding="utf-8")
    assert 'value="auto" selected>Smart Auto' in html
    assert 'id="voiceReviewToggle"' in html
    assert 'id="editBanner"' in html
    assert "AUTO — Strongest Installed Model" in desktop_js
    assert "normalizeModelAutoLabel" in desktop_js
    assert "Edit & resend" in js
    assert "edit_message_id" in js


class StreamingGateway(TextOnlyGateway):
    async def chat_stream(self, *, on_token=None, **kwargs):
        self.calls += 1
        for token in ("DPN ", "AI ", "streaming"):
            if on_token:
                result = on_token(token)
                if asyncio.iscoroutine(result):
                    await result
        return {"message": {"role": "assistant", "content": "DPN AI streaming"}}


def test_fast_chat_streams_tokens_without_tool_schema(tmp_path: Path):
    settings, db, tools = make_stack(tmp_path)
    gateway = StreamingGateway()
    events = []

    async def run():
        return await DPNAIAgent(settings, db, gateway, tools).run(
            conversation_id=None,
            user_message="Explain what an API is in simple terms",
            event_callback=lambda event: events.append(event),
        )

    result = asyncio.run(run())
    assert result.message == "DPN AI streaming"
    assert "".join(event.get("text", "") for event in events if event.get("type") == "token") == "DPN AI streaming"
    assert gateway.calls == 1


def test_maximum_mode_uses_auto_model_request_when_no_explicit_model(tmp_path: Path):
    settings, db, tools = make_stack(tmp_path)
    gateway = TextOnlyGateway()
    asyncio.run(DPNAIAgent(settings, db, gateway, tools).run(conversation_id=None, user_message="Explain local AI"))
    assert gateway.selected
    assert gateway.selected[0][0] == "__maximum__"


def test_ui_uses_streaming_chat_endpoint():
    root = Path(__file__).resolve().parents[1]
    js = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "'/api/chat/stream'" in js
    assert "event.type === 'token'" in js
