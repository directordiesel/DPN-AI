from __future__ import annotations

from app.capability_marketplace_v10 import CapabilityMarketplace, MarketplaceManifest


def _manifest(payload):
    return MarketplaceManifest(
        package_id=str(payload.get("package_id", "")),
        version=str(payload.get("version", "")),
        publisher_id=str(payload.get("publisher_id", "")),
        source_uri=str(payload.get("source_uri", "")),
        code_sha256=str(payload.get("code_sha256", "")),
        declared_tools=tuple(payload.get("declared_tools", []) or []),
        requested_risks=tuple(payload.get("requested_risks", []) or []),
        minimum_dpn_version=str(payload.get("minimum_dpn_version", "10.0.0")),
        maximum_dpn_major=int(payload.get("maximum_dpn_major", 10)),
    )


def register(registry):
    marketplace = CapabilityMarketplace(registry.forge, registry.settings.data_dir)
    registry.capability_marketplace_v10 = marketplace

    manifest_schema = {
        "type": "object",
        "properties": {
            "package_id": {"type": "string"},
            "version": {"type": "string"},
            "publisher_id": {"type": "string"},
            "source_uri": {"type": "string"},
            "code_sha256": {"type": "string"},
            "declared_tools": {"type": "array", "items": {"type": "string"}, "default": []},
            "requested_risks": {"type": "array", "items": {"type": "string"}, "default": []},
            "minimum_dpn_version": {"type": "string", "default": "10.0.0"},
            "maximum_dpn_major": {"type": "integer", "default": 10},
        },
        "required": ["package_id", "version", "publisher_id", "source_uri", "code_sha256"],
        "additionalProperties": False,
    }

    registry.register(
        name="list_marketplace_packages_v10",
        description="List governed capability marketplace evidence without executing plugin code.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        function=marketplace.list_packages,
        risk="read",
    )
    registry.register(
        name="inspect_marketplace_package_v10",
        description="Validate v10 marketplace metadata, trust, compatibility, and exact code digest without executing code.",
        parameters={
            "type": "object",
            "properties": {"manifest": manifest_schema, "code": {"type": "string"}},
            "required": ["manifest", "code"],
            "additionalProperties": False,
        },
        function=lambda manifest, code: marketplace.inspect_manifest(_manifest(manifest), code),
        risk="read",
    )
    registry.register(
        name="stage_marketplace_package_v10",
        description="Stage a host-trusted, v10-compatible marketplace package through CapabilityForge; never activates it.",
        parameters={
            "type": "object",
            "properties": {"manifest": manifest_schema, "code": {"type": "string"}, "description": {"type": "string", "default": ""}},
            "required": ["manifest", "code"],
            "additionalProperties": False,
        },
        function=lambda manifest, code, description="": marketplace.stage(_manifest(manifest), code, description),
        risk="write",
    )
    registry.register(
        name="validate_marketplace_package_v10",
        description="Revalidate a staged marketplace package and its immutable digest evidence without executing it.",
        parameters={
            "type": "object",
            "properties": {"package_id": {"type": "string"}},
            "required": ["package_id"],
            "additionalProperties": False,
        },
        function=marketplace.validate_staged,
        risk="read",
    )
    registry.register(
        name="promote_marketplace_package_v10",
        description="Promote a revalidated marketplace package into the trusted local plugin directory. This high-risk activation remains approval controlled and requires restart.",
        parameters={
            "type": "object",
            "properties": {"package_id": {"type": "string"}},
            "required": ["package_id"],
            "additionalProperties": False,
        },
        function=marketplace.promote,
        gate="commands",
        risk="destructive",
    )
    registry.register(
        name="rollback_marketplace_package_v10",
        description="Restore a prior CapabilityForge backup for a marketplace plugin while preserving rollback evidence. Approval controlled.",
        parameters={
            "type": "object",
            "properties": {"package_id": {"type": "string"}, "backup_name": {"type": ["string", "null"], "default": None}},
            "required": ["package_id"],
            "additionalProperties": False,
        },
        function=marketplace.rollback,
        gate="commands",
        risk="destructive",
    )
