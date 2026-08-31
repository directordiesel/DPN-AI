from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


def load_plugins(plugin_dir: Path, registry: Any) -> list[dict[str, str]]:
    """Load local Python plugins exposing register(registry). Disabled/example files are ignored."""
    errors: list[dict[str, str]] = []
    plugin_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(plugin_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        module_name = f"dpn_ai_plugin_{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise RuntimeError("Cannot create plugin module specification")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            register = getattr(module, "register", None)
            if not callable(register):
                raise RuntimeError("Plugin must define register(registry)")
            register(registry)
        except Exception as exc:  # noqa: BLE001
            errors.append({"plugin": path.name, "error": f"{type(exc).__name__}: {exc}"})
    return errors