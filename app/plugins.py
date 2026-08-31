from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Any


MAX_PLUGIN_BYTES = 1_000_000


def load_plugins(plugin_dir: Path, registry: Any) -> list[dict[str, str]]:
    """Load trusted local Python plugins exposing register(registry).

    Plugin files must be regular, non-symlinked files directly inside the
    configured plugin directory. Disabled/example files are ignored.
    """
    errors: list[dict[str, str]] = []
    plugin_dir.mkdir(parents=True, exist_ok=True)
    root = plugin_dir.resolve()

    for path in sorted(plugin_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            if path.is_symlink():
                raise RuntimeError("Plugin symlinks are not allowed")
            resolved = path.resolve(strict=True)
            if resolved.parent != root or not resolved.is_file():
                raise RuntimeError("Plugin must be a regular file directly inside the plugin directory")
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
        except Exception as exc:  # noqa: BLE001
            errors.append({"plugin": path.name, "error": f"{type(exc).__name__}: {exc}"})
    return errors
