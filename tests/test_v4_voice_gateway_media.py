from __future__ import annotations

import io
import zipfile

import pytest
from pathlib import Path
from unittest import mock

from app.archive_tools import ArchiveTools
from app.config import Settings
from app.db import Database
from app.media import MediaTools
from app.model_gateway import ModelGateway
from app.vault import SecretVault
from app.voice_adapter import VoiceAdapter


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "data_dir": tmp_path / "data",
        "workspace_dir": tmp_path / "workspace",
        "skills_dir": tmp_path / "skills",
        "vault_key_path": tmp_path / "data" / "vault.key",
        "compatible_api_url": "http://127.0.0.1:1234",
    }
    values.update(overrides)
    return Settings(**values)


def test_voice_profiles_are_original_and_distinct(tmp_path: Path):
    adapter = VoiceAdapter(tmp_path / "workspace", tmp_path / "data")
    payload = adapter.profiles()
    profiles = {item["id"]: item for item in payload["profiles"]}
    assert profiles["sentinel"]["gender"] == "male"
    assert "British-inspired" in profiles["sentinel"]["style"]
    assert "not an imitation" in profiles["sentinel"]["description"]
    assert profiles["aurora"]["gender"] == "female"
    assert "Soft" in profiles["aurora"]["style"]


def test_voice_markdown_is_cleaned_for_read_aloud(tmp_path: Path):
    adapter = VoiceAdapter(tmp_path / "workspace", tmp_path / "data")
    cleaned = adapter._speech_text("# Report\n- **Ready**\n```python\nprint('secret')\n```\n[Open](https://example.com)")
    assert "#" not in cleaned
    assert "**" not in cleaned
    assert "print('secret')" not in cleaned
    assert "Ready" in cleaned and "Open" in cleaned


def test_voice_upload_is_bounded_to_workspace(tmp_path: Path):
    adapter = VoiceAdapter(tmp_path / "workspace", tmp_path / "data")
    relative = adapter.save_upload(b"audio-bytes", "../../capture.exe")
    target = (tmp_path / "workspace" / relative).resolve()
    target.relative_to((tmp_path / "workspace").resolve())
    assert target.suffix == ".webm"
    assert target.read_bytes() == b"audio-bytes"


def test_model_gateway_routes_explicit_providers(tmp_path: Path):
    settings = make_settings(tmp_path)
    db = Database(settings.database_path)
    vault = SecretVault(settings.vault_key_path, settings.data_dir / "secrets.json")
    gateway = ModelGateway(settings, db, vault)
    assert gateway.resolve_model("ollama:qwen") == ("ollama", "qwen")
    assert gateway.resolve_model("compatible:local-model") == ("compatible", "local-model")
    assert gateway.resolve_model("openai:remote-model") == ("compatible", "remote-model")
    assert gateway._api_root("http://localhost:1234") == "http://localhost:1234/v1"
    assert gateway._api_root("http://localhost:1234/v1/") == "http://localhost:1234/v1"



def test_model_gateway_allows_keyless_local_compatible_server(tmp_path: Path):
    settings = make_settings(tmp_path)
    db = Database(settings.database_path)
    vault = SecretVault(settings.vault_key_path, settings.data_dir / "secrets.json")
    gateway = ModelGateway(settings, db, vault)
    assert gateway._compatible_headers() == {"Content-Type": "application/json"}

def test_model_gateway_normalizes_tool_calls():
    payload = {
        "id": "request-1",
        "model": "test-model",
        "choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call-1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"README.md"}'},
        }]}}],
    }
    result = ModelGateway._normalize_compatible_response(payload, "fallback")
    call = result["message"]["tool_calls"][0]
    assert call["function"]["name"] == "read_file"
    assert call["function"]["arguments"] == {"path": "README.md"}
    assert result["provider"] == "compatible"


def test_archive_inspection_rejects_traversal(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    archive_path = workspace / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escape.txt", "bad")
    tools = ArchiveTools(workspace)
    report = tools.inspect("unsafe.zip")
    assert report["unsafe_entries"] == ["../escape.txt"]
    extracted = tools.extract("unsafe.zip")
    assert not extracted["ok"]
    assert not (tmp_path / "escape.txt").exists()


def test_archive_extracts_normal_zip(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    archive_path = workspace / "safe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("project/readme.txt", "DPN AI")
    tools = ArchiveTools(workspace)
    result = tools.extract("safe.zip")
    assert result["ok"]
    assert (workspace / result["path"] / "project" / "readme.txt").read_text() == "DPN AI"


def test_media_capabilities_are_reported_without_ffmpeg(tmp_path: Path):
    status = MediaTools(tmp_path / "workspace").status()
    assert status["ok"] is True
    assert ".mp4" in status["video_formats"]
    assert ".wav" in status["audio_formats"]
    assert "ffmpeg" in status and "ffprobe" in status


def _gateway(tmp_path: Path, **settings_overrides) -> ModelGateway:
    settings = make_settings(tmp_path, **settings_overrides)
    db = Database(settings.database_path)
    vault = SecretVault(settings.vault_key_path, settings.data_dir / "secrets.json")
    return ModelGateway(settings, db, vault)


def test_model_gateway_rejects_embedded_credentials_and_url_metadata(tmp_path: Path):
    gateway = _gateway(tmp_path, compatible_api_url="https://user:secret@example.test/v1", allow_external_models_default=True)
    with pytest.raises(Exception, match="embedded credentials"):
        gateway._ensure_compatible_allowed()

    gateway = _gateway(tmp_path, compatible_api_url="https://example.test/v1?token=abc", allow_external_models_default=True)
    with pytest.raises(Exception, match="query string"):
        gateway._ensure_compatible_allowed()

    gateway = _gateway(tmp_path, compatible_api_url="https://example.test/v1#fragment", allow_external_models_default=True)
    with pytest.raises(Exception, match="fragment"):
        gateway._ensure_compatible_allowed()


def test_model_gateway_requires_https_for_public_external_endpoints(tmp_path: Path):
    gateway = _gateway(tmp_path, compatible_api_url="http://example.test/v1", allow_external_models_default=True)
    public = [(2, 1, 6, "", ("93.184.216.34", 80))]
    with mock.patch("app.model_gateway.socket.getaddrinfo", return_value=public):
        with pytest.raises(Exception, match="must use HTTPS"):
            gateway._ensure_compatible_allowed()


def test_model_gateway_blocks_public_endpoint_until_explicitly_enabled(tmp_path: Path):
    gateway = _gateway(tmp_path, compatible_api_url="https://example.test/v1", allow_external_models_default=False)
    public = [(2, 1, 6, "", ("93.184.216.34", 443))]
    with mock.patch("app.model_gateway.socket.getaddrinfo", return_value=public):
        with pytest.raises(Exception, match="disabled"):
            gateway._ensure_compatible_allowed()


def test_model_gateway_allows_explicit_https_public_endpoint(tmp_path: Path):
    gateway = _gateway(tmp_path, compatible_api_url="https://example.test/v1", allow_external_models_default=True)
    public = [(2, 1, 6, "", ("93.184.216.34", 443))]
    with mock.patch("app.model_gateway.socket.getaddrinfo", return_value=public):
        assert gateway._ensure_compatible_allowed() == "https://example.test/v1"


def test_model_gateway_rejects_mixed_public_private_dns_answers(tmp_path: Path):
    gateway = _gateway(tmp_path, compatible_api_url="https://example.test/v1", allow_external_models_default=True)
    mixed = [
        (2, 1, 6, "", ("93.184.216.34", 443)),
        (2, 1, 6, "", ("127.0.0.1", 443)),
    ]
    with mock.patch("app.model_gateway.socket.getaddrinfo", return_value=mixed):
        with pytest.raises(Exception, match="mixed public/private"):
            gateway._ensure_compatible_allowed()


def test_model_gateway_rejects_link_local_metadata_addresses(tmp_path: Path):
    gateway = _gateway(tmp_path, compatible_api_url="http://169.254.169.254/v1", allow_external_models_default=True)
    with pytest.raises(Exception, match="reserved or link-local"):
        gateway._ensure_compatible_allowed()
