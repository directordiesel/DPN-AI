from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Any


MAX_PLUGIN_BYTES = 1_000_000
MANDATORY_PLUGIN_NAMES = {"approval_payload_security.py"}


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


def _is_runtime_tool_registry(registry: Any) -> bool:
    """Identify the real DPN AI tool registry without coupling to its class import.

    Loader unit tests and third-party utility uses may pass a tiny stand-in object
    purely to test path handling. Mandatory runtime protections should be required
    only for a registry that exposes the production security dependencies.
    """
    return all(hasattr(registry, name) for name in ("db", "vault", "tools", "execute", "execute_approval"))


def load_plugins(plugin_dir: Path, registry: Any) -> list[dict[str, str]]:
    """Load trusted local Python plugins exposing register(registry).

    User-configured plugins are restricted to regular files directly inside the
    configured directory. For the production ToolRegistry, security-critical
    bundled plugins are always loaded from the application's own plugin directory
    even when DPN_PLUGINS_DIR points elsewhere. A mandatory registration failure
    fails closed. Lightweight loader test doubles do not activate runtime-only
    security extensions.
    """
    errors: list[dict[str, str]] = []
    plugin_dir.mkdir(parents=True, exist_ok=True)
    configured_root = plugin_dir.resolve()
    bundled_root = (Path(__file__).resolve().parent.parent / "plugins").resolve()
    require_mandatory = _is_runtime_tool_registry(registry)

    candidates: list[tuple[Path, Path, bool]] = []
    if require_mandatory:
        for name in sorted(MANDATORY_PLUGIN_NAMES):
            mandatory = bundled_root / name
            if mandatory.exists():
                candidates.append((mandatory, bundled_root, True))
            else:
                error = {"plugin": name, "error": "RuntimeError: mandatory security plugin is missing"}
                errors.append(error)
                raise RuntimeError(f"Mandatory security plugin is missing: {name}")

    for path in sorted(plugin_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            resolved = path.resolve(strict=True)
        except Exception:
            resolved = path
        if any(existing.resolve() == resolved for existing, _, _ in candidates if existing.exists()):
            continue
        candidates.append((path, configured_root, False))

    for path, expected_parent, mandatory in candidates:
        try:
            _load_plugin(path, expected_parent, registry)
        except Exception as exc:  # noqa: BLE001
            prefix = "mandatory security plugin" if mandatory else "plugin"
            errors.append({"plugin": path.name, "error": f"{prefix} failed: {type(exc).__name__}: {exc}"})
            if mandatory:
                # Security-critical registration failures must fail closed rather
                # than starting DPN AI with the protection silently disabled.
                raise RuntimeError(f"Mandatory security plugin failed: {path.name}") from exc
    return errors
