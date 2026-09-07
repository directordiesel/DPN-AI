from __future__ import annotations

from app.capability_marketplace_v10 import CapabilityMarketplace, CapabilityMarketplaceError, MarketplaceManifest
from app.marketplace_activation_v10 import SignedMarketplaceController
from app.marketplace_trust_v10 import (
    CatalogEntry,
    MarketplaceTrustVerifier,
    PackageSignature,
    PublisherKey,
    PublisherTrustStore,
    SignedCatalog,
)


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


def _package_signature(payload):
    return PackageSignature(
        publisher_id=str(payload.get("publisher_id", "")),
        key_id=str(payload.get("key_id", "")),
        signature_b64=str(payload.get("signature_b64", "")),
    )


def _catalog(payload):
    entries = tuple(
        CatalogEntry(
            package_id=str(item.get("package_id", "")),
            version=str(item.get("version", "")),
            manifest_sha256=str(item.get("manifest_sha256", "")),
        )
        for item in (payload.get("entries", []) or [])
    )
    return SignedCatalog(
        publisher_id=str(payload.get("publisher_id", "")),
        key_id=str(payload.get("key_id", "")),
        generated_at=float(payload.get("generated_at", 0)),
        expires_at=float(payload.get("expires_at", 0)),
        entries=entries,
        signature_b64=str(payload.get("signature_b64", "")),
        schema_version=int(payload.get("schema_version", 1)),
    )


def _host_controller(registry, marketplace):
    raw_keys = getattr(registry, "marketplace_publisher_keys_v10", ()) or ()
    keys = []
    for item in raw_keys:
        if isinstance(item, PublisherKey):
            keys.append(item)
        elif isinstance(item, dict):
            keys.append(PublisherKey(**item))
        else:
            raise CapabilityMarketplaceError("host marketplace publisher key configuration is malformed")
    if not keys:
        return None
    return SignedMarketplaceController(marketplace, MarketplaceTrustVerifier(PublisherTrustStore(keys)))


def _require_controller(registry):
    controller = getattr(registry, "signed_capability_marketplace_v10", None)
    if controller is None:
        raise CapabilityMarketplaceError("signed marketplace trust roots are not configured by the host")
    return controller


def _live_catalog(registry):
    catalog = registry.catalog()
    if not isinstance(catalog, list):
        raise CapabilityMarketplaceError("live ToolRegistry catalog is unavailable")
    return catalog


def register(registry):
    marketplace = CapabilityMarketplace(registry.forge, registry.settings.data_dir)
    registry.capability_marketplace_v10 = marketplace
    registry.signed_capability_marketplace_v10 = _host_controller(registry, marketplace)

    manifest_schema = {
        "type": "object",
        "properties": {
            "package_id": {"type": "string"}, "version": {"type": "string"}, "publisher_id": {"type": "string"},
            "source_uri": {"type": "string"}, "code_sha256": {"type": "string"},
            "declared_tools": {"type": "array", "items": {"type": "string"}, "default": []},
            "requested_risks": {"type": "array", "items": {"type": "string"}, "default": []},
            "minimum_dpn_version": {"type": "string", "default": "10.0.0"},
            "maximum_dpn_major": {"type": "integer", "default": 10},
        },
        "required": ["package_id", "version", "publisher_id", "source_uri", "code_sha256"],
        "additionalProperties": False,
    }
    signature_schema = {
        "type": "object",
        "properties": {"publisher_id": {"type": "string"}, "key_id": {"type": "string"}, "signature_b64": {"type": "string"}},
        "required": ["publisher_id", "key_id", "signature_b64"], "additionalProperties": False,
    }
    catalog_schema = {
        "type": "object",
        "properties": {
            "publisher_id": {"type": "string"}, "key_id": {"type": "string"},
            "generated_at": {"type": "number"}, "expires_at": {"type": "number"}, "signature_b64": {"type": "string"},
            "schema_version": {"type": "integer", "default": 1},
            "entries": {"type": "array", "items": {"type": "object", "properties": {
                "package_id": {"type": "string"}, "version": {"type": "string"}, "manifest_sha256": {"type": "string"}},
                "required": ["package_id", "version", "manifest_sha256"], "additionalProperties": False}},
        },
        "required": ["publisher_id", "key_id", "generated_at", "expires_at", "entries", "signature_b64"],
        "additionalProperties": False,
    }

    registry.register(name="list_marketplace_packages_v10", description="List governed capability marketplace evidence without executing plugin code.", parameters={"type": "object", "properties": {}, "additionalProperties": False}, function=marketplace.list_packages, risk="read")
    registry.register(name="inspect_marketplace_package_v10", description="Validate v10 marketplace metadata and exact code digest without executing code. Inspection is non-authorizing and does not replace signed admission.", parameters={"type": "object", "properties": {"manifest": manifest_schema, "code": {"type": "string"}}, "required": ["manifest", "code"], "additionalProperties": False}, function=lambda manifest, code: marketplace.inspect_manifest(_manifest(manifest), code), risk="read")

    def stage_signed(manifest, code, package_signature, catalog, description=""):
        return _require_controller(registry).stage_signed(
            manifest=_manifest(manifest), code=code, package_signature=_package_signature(package_signature),
            catalog=_catalog(catalog), live_tool_catalog=_live_catalog(registry), description=description,
        )

    registry.register(name="stage_marketplace_package_v10", description="Stage a cryptographically signed, signed-catalog-bound v10 marketplace package after live ToolRegistry contract validation; never activates it.", parameters={"type": "object", "properties": {"manifest": manifest_schema, "code": {"type": "string"}, "package_signature": signature_schema, "catalog": catalog_schema, "description": {"type": "string", "default": ""}}, "required": ["manifest", "code", "package_signature", "catalog"], "additionalProperties": False}, function=stage_signed, risk="write")
    registry.register(name="validate_marketplace_package_v10", description="Revalidate a staged marketplace package and immutable code digest without executing it.", parameters={"type": "object", "properties": {"package_id": {"type": "string"}}, "required": ["package_id"], "additionalProperties": False}, function=marketplace.validate_staged, risk="read")

    def promote_signed(package_id):
        return _require_controller(registry).promote_signed(package_id, live_tool_catalog=_live_catalog(registry))

    registry.register(name="promote_marketplace_package_v10", description="Reverify signed admission, current key/catalog trust, staged digest, and live ToolRegistry contract before approval-controlled activation. Requires restart.", parameters={"type": "object", "properties": {"package_id": {"type": "string"}}, "required": ["package_id"], "additionalProperties": False}, function=promote_signed, gate="commands", risk="destructive")
    registry.register(name="rollback_marketplace_package_v10", description="Restore a prior CapabilityForge backup for a marketplace plugin while preserving rollback evidence. Approval controlled.", parameters={"type": "object", "properties": {"package_id": {"type": "string"}, "backup_name": {"type": ["string", "null"], "default": None}}, "required": ["package_id"], "additionalProperties": False}, function=marketplace.rollback, gate="commands", risk="destructive")
