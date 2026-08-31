from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from app.agent import DPNAIAgent
from app.config import Settings
from app.db import Database
from app.ollama_client import OllamaClient
from app.orchestrator import MissionOrchestrator
from app.tools.registry import ToolRegistry


class CaptureGateway:
    def __init__(self, content: str = "Hello. DPN AI is online.") -> None:
        self.requests: list[dict] = []
        self.content = content

    async def chat(self, **kwargs):
        self.requests.append(kwargs)
        return {"message": {"role": "assistant", "content": self.content}}


def make_stack(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        skills_dir=tmp_path / "skills",
        plugins_dir=tmp_path / "plugins",
        vault_key_path=tmp_path / "data" / "vault.key",
        static_dir=Path(__file__).resolve().parents[1] / "app" / "static",
        default_model="fake-model",
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.database_path)
    tools = ToolRegistry(settings, db)
    return settings, db, tools


def test_greeting_uses_minimal_no_tool_model_request(tmp_path: Path):
    settings, db, tools = make_stack(tmp_path)
    gateway = CaptureGateway()
    result = asyncio.run(
        DPNAIAgent(settings, db, gateway, tools).run(
            conversation_id=None,
            user_message="hi",
            profile="auto",
        )
    )
    assert result.message.startswith("Hello")
    assert len(gateway.requests) == 1
    assert gateway.requests[0]["tools"] is None


def test_reviewer_accepts_raw_objective_without_attribute_error(tmp_path: Path):
    settings, db, tools = make_stack(tmp_path)
    gateway = CaptureGateway(
        '{"verdict":"pass","confidence":0.9,"summary":"Greeting verified",'
        '"verified":["response exists"],"missing":[],"contradictions":[],"recommended_next_actions":[]}'
    )
    agent = DPNAIAgent(settings, db, gateway, tools)
    orchestrator = MissionOrchestrator(settings, db, gateway, agent)
    result = asyncio.run(orchestrator.review("hi", [{"message": "hello"}], "fake-model"))
    assert result["verdict"] == "pass"
    assert result["evaluator"] == "security"


def test_ollama_tool_schema_normalizer_removes_nullable_types_and_defaults():
    tools = [{
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "end_line": {"type": ["integer", "null"], "default": None},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    }]
    normalized = OllamaClient.normalize_tools(tools)
    end_line = normalized[0]["function"]["parameters"]["properties"]["end_line"]
    assert end_line["type"] == "integer"
    assert "default" not in end_line


class RetryClient(OllamaClient):
    def __init__(self):
        super().__init__("http://127.0.0.1:11434")
        self.payloads: list[dict] = []

    async def _post_chat(self, payload: dict) -> httpx.Response:
        self.payloads.append(payload)
        request = httpx.Request("POST", "http://127.0.0.1:11434/api/chat")
        if len(self.payloads) == 1:
            return httpx.Response(500, text="Internal Server Error", request=request)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "Recovered"}}, request=request)


def test_ollama_retries_without_string_thinking_after_internal_error():
    client = RetryClient()
    result = asyncio.run(client.chat(model="test", messages=[{"role": "user", "content": "hi"}], think="medium"))
    assert result["message"]["content"] == "Recovered"
    assert client.payloads[0]["think"] == "medium"
    assert "think" not in client.payloads[1]