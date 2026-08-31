import asyncio
from pathlib import Path

from app.agent import DPNAIAgent
from app.config import Settings
from app.db import Database
from app.tools.registry import ToolRegistry


class FakeOllama:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {"name": "make_directory", "arguments": {"path": "project"}},
                        }
                    ],
                }
            }
        return {"message": {"role": "assistant", "content": "Created the project directory."}}


def test_agent_executes_tool_loop(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        static_dir=Path(__file__).resolve().parents[1] / "app" / "static",
        default_model="fake-model",
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.database_path)
    tools = ToolRegistry(settings, db)
    result = asyncio.run(
        DPNAIAgent(settings, db, FakeOllama(), tools).run(
            conversation_id=None,
            user_message="Create a project directory",
        )
    )
    assert result.message == "Created the project directory."
    assert result.traces[0].name == "make_directory"
    assert result.traces[0].ok is True
    assert (settings.workspace_dir / "project").is_dir()


class CaptureOllama:
    def __init__(self) -> None:
        self.request = None

    async def chat(self, **kwargs):
        self.request = kwargs
        return {"message": {"role": "assistant", "content": "Attachment received."}}


def test_agent_injects_document_and_image_attachments(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        static_dir=Path(__file__).resolve().parents[1] / "app" / "static",
        default_model="fake-vision-model",
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    (settings.workspace_dir / "notes.txt").write_text("DPN attachment context", encoding="utf-8")
    (settings.workspace_dir / "image.png").write_bytes(b"fake-png-bytes")
    db = Database(settings.database_path)
    tools = ToolRegistry(settings, db)
    ollama = CaptureOllama()
    result = asyncio.run(
        DPNAIAgent(settings, db, ollama, tools).run(
            conversation_id=None,
            user_message="Analyze these files",
            attachments=["notes.txt", "image.png"],
        )
    )
    assert result.message == "Attachment received."
    assert ollama.request is not None
    messages = ollama.request["messages"]
    assert "DPN attachment context" in messages[0]["content"]
    current_user = next(message for message in reversed(messages) if message["role"] == "user")
    assert current_user["images"]
    assert "notes.txt" in current_user["content"]
    conversation_id = result.conversation_id
    stored = db.get_messages(conversation_id)
    assert stored[0]["metadata"]["attachments"] == ["notes.txt", "image.png"]