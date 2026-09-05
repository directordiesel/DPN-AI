from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

from app.tools.image_runtime import install_image_tools
from app.tools.research import install_research_tools
from app.voice_security import install_voice_security


MAX_PLUGIN_BYTES = 1_000_000


def _load_plugin(path: Path, expected_parent: Path, registry: Any) -> None:
    if path.is_symlink():
        raise RuntimeError("Plugin symlinks are not allowed")
    resolved = path.resolve(strict=True)
    if resolved.parent != expected_parent or not resolved.is_file():
        raise RuntimeError("Plugin must be a regular file directly inside the approved plugin directory")
    if resolved.stat().st_size > MAX_PLUGIN_BYTES:
        raise RuntimeError(f"Plugin exceeds {MAX_PLUGIN_BYTES:,} bytes")

    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()[:16]
    module_name = f"dpn_ai_plugin_{path.stem}_{digest}"
    spec = importlib.util.spec_from_file_location(module_name, resolved)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot create plugin module specification")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        register = getattr(module, "register", None)
        if not callable(register):
            raise RuntimeError("Plugin must define register(registry)")
        register(registry)
    except Exception:
        sys.modules.pop(module_name, None)
        raise


def load_plugins(plugin_dir: Path, registry: Any) -> list[dict[str, str]]:
    """Install core runtime capabilities, then load optional trusted local plugins.

    Voice hardening, v9 research intelligence, and v9 image intelligence are
    installed here as core initialization hooks after the ToolRegistry has
    registered its built-in callbacks. They do not depend on files in
    DPN_PLUGINS_DIR, while optional plugins remain restricted to regular files
    directly inside that directory and cannot be symlinks.
    """
    install_voice_security(registry)
    install_research_tools(registry)
    install_image_tools(registry)

    errors: list[dict[str, str]] = []
    plugin_dir.mkdir(parents=True, exist_ok=True)
    configured_root = plugin_dir.resolve()

    for path in sorted(plugin_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            _load_plugin(path, configured_root, registry)
        except Exception as exc:  # noqa: BLE001
            errors.append({"plugin": path.name, "error": f"plugin failed: {type(exc).__name__}: {exc}"})
    return errors
