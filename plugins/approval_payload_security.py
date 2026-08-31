from __future__ import annotations

from typing import Any

from app.approval_security import ApprovalSecurity


def register(registry: Any) -> None:
    """Compatibility shim for older plugin-based approval protection.

    Modern DPN AI installs initialize ApprovalSecurity directly from ToolRegistry,
    so this bundled plugin normally has nothing to do. Keeping the shim preserves
    compatibility for isolated tools/tests that still load the historical plugin
    explicitly without making production security depend on plugin discovery.
    """
    if getattr(registry, "approval_security", None) is None:
        registry.approval_security = ApprovalSecurity(registry)
        registry.execute = registry.approval_security.execute
        registry.execute_approval = registry.approval_security.execute_approval
