from pathlib import Path
from types import SimpleNamespace

import pytest

from app.tools.image_runtime import ImageProviderRuntime, install_image_tools


@pytest.mark.asyncio
async def test_generation_uses_configured_provider(tmp_path: Path):
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "path": "generated/images/test.png"}

    runtime = ImageProviderRuntime(tmp_path, generate=generate)
    result = await runtime.execute("generate", "Create a purple logo", width=1024, height=1024)
    assert result["ok"] is True
    assert result["provider_capability"] == "text_to_image"
    assert calls and calls[0]["prompt"] == "Create a purple logo"


@pytest.mark.asyncio
async def test_edit_and_vision_fail_closed_without_provider(tmp_path: Path):
    source = tmp_path / "source.png"
    source.write_bytes(b"fake")
    runtime = ImageProviderRuntime(tmp_path)

    edit = await runtime.execute("edit", "Remove background", source_path="source.png")
    vision = await runtime.execute("analyze", "Describe the UI", source_path="source.png")

    assert edit["ok"] is False
    assert edit["provider_capability"] == "image_edit"
    assert vision["ok"] is False
    assert vision["provider_capability"] == "vision"


def test_capabilities_are_explicit(tmp_path: Path):
    runtime = ImageProviderRuntime(tmp_path, generate=lambda **_: {"ok": True})
    result = runtime.capabilities()
    assert result["capabilities"] == {
        "text_to_image": True,
        "image_edit": False,
        "vision": False,
    }
    assert result["policy"]["unsupported_capabilities_fail_closed"] is True


def test_installer_registers_core_tools(tmp_path: Path):
    registered = {}

    class Registry:
        settings = SimpleNamespace(workspace_dir=tmp_path)
        images = SimpleNamespace(generate=lambda **_: {"ok": True})

        def register(self, name, description, parameters, function, gate=None, risk="read"):
            registered[name] = {"gate": gate, "risk": risk, "schema": parameters, "function": function}

    registry = Registry()
    runtime = install_image_tools(registry)

    assert runtime is registry.image_runtime
    assert set(registered) == {"image_capabilities", "plan_image_operation", "execute_image_operation"}
    assert registered["execute_image_operation"]["gate"] == "images"
    assert registered["execute_image_operation"]["risk"] == "external"
    assert registered["plan_image_operation"]["risk"] == "read"


def test_installer_ignores_minimal_plugin_loader_stub():
    assert install_image_tools(SimpleNamespace()) is None
