from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.capability_marketplace_v10 import CapabilityMarketplace, MarketplaceManifest
from app.marketplace_trust_v10 import (
    CatalogEntry,
    MarketplaceTrustError,
    MarketplaceTrustVerifier,
    PackageSignature,
    SignedCatalog,
    validate_live_tool_contract,
)


class SignedMarketplaceController:
    """Durable signed admission and approval-preserving promotion controller."""

    SCHEMA_VERSION = 1

    def __init__(self, marketplace: CapabilityMarketplace, verifier: MarketplaceTrustVerifier) -> None:
        self.marketplace = marketplace
        self.verifier = verifier

    def _path(self, package_id: str) -> Path:
        evidence = self.marketplace.get_evidence(package_id)
        return self.marketplace.state_dir / f"{evidence.package_id}.signed.json"

    @staticmethod
    def _catalog_payload(catalog: SignedCatalog) -> dict[str, Any]:
        return {
            "publisher_id": catalog.publisher_id,
            "key_id": catalog.key_id,
            "generated_at": catalog.generated_at,
            "expires_at": catalog.expires_at,
            "entries": [asdict(item) for item in catalog.entries],
            "signature_b64": catalog.signature_b64,
            "schema_version": catalog.schema_version,
        }

    @staticmethod
    def _catalog_from(payload: Mapping[str, Any]) -> SignedCatalog:
        try:
            entries = tuple(CatalogEntry(**item) for item in payload["entries"])
            return SignedCatalog(
                publisher_id=str(payload["publisher_id"]),
                key_id=str(payload["key_id"]),
                generated_at=float(payload["generated_at"]),
                expires_at=float(payload["expires_at"]),
                entries=entries,
                signature_b64=str(payload["signature_b64"]),
                schema_version=int(payload.get("schema_version", 1)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MarketplaceTrustError("signed marketplace catalog receipt is malformed") from exc

    def stage_signed(
        self,
        *,
        manifest: MarketplaceManifest,
        code: str,
        package_signature: PackageSignature,
        catalog: SignedCatalog,
        live_tool_catalog: Sequence[Mapping[str, Any]],
        description: str = "",
        now: float | None = None,
    ) -> dict[str, Any]:
        package_trust = self.verifier.verify_package(manifest, package_signature)
        catalog_trust = self.verifier.verify_catalog_membership(manifest, catalog, now=now)
        tool_contract = validate_live_tool_contract(manifest, live_tool_catalog)
        staged = self.marketplace.stage(manifest, code, description=description)
        if not staged.get("ok"):
            return staged
        evidence = self.marketplace.get_evidence(manifest.package_id)
        receipt = {
            "schema_version": self.SCHEMA_VERSION,
            "recorded_at": time.time(),
            "manifest": asdict(manifest.normalized()),
            "package_signature": asdict(package_signature),
            "catalog": self._catalog_payload(catalog),
            "manifest_sha256": package_trust["manifest_sha256"],
            "catalog_sha256": catalog_trust["catalog_sha256"],
            "code_sha256": evidence.code_sha256,
        }
        self.marketplace._atomic_json(self._path(manifest.package_id), receipt)
        return {
            **staged,
            "signed_admission": {
                "signature_verified": True,
                "catalog_member": True,
                "manifest_sha256": receipt["manifest_sha256"],
                "catalog_sha256": receipt["catalog_sha256"],
            },
            "tool_contract": tool_contract,
            "execution_authorized": False,
        }

    def _load_receipt(self, package_id: str) -> dict[str, Any]:
        path = self._path(package_id)
        if not path.is_file() or path.is_symlink():
            raise MarketplaceTrustError("signed marketplace admission evidence is missing")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MarketplaceTrustError("signed marketplace admission evidence is corrupt") from exc
        if payload.get("schema_version") != self.SCHEMA_VERSION:
            raise MarketplaceTrustError("signed marketplace admission schema is unsupported")
        return payload

    def promote_signed(
        self,
        package_id: str,
        *,
        live_tool_catalog: Sequence[Mapping[str, Any]],
        now: float | None = None,
    ) -> dict[str, Any]:
        receipt = self._load_receipt(package_id)
        try:
            manifest = MarketplaceManifest(**receipt["manifest"])
            signature = PackageSignature(**receipt["package_signature"])
            catalog = self._catalog_from(receipt["catalog"])
        except (KeyError, TypeError, ValueError) as exc:
            raise MarketplaceTrustError("signed marketplace admission receipt is malformed") from exc

        package_trust = self.verifier.verify_package(manifest, signature)
        catalog_trust = self.verifier.verify_catalog_membership(manifest, catalog, now=now)
        if package_trust["manifest_sha256"] != receipt.get("manifest_sha256"):
            raise MarketplaceTrustError("signed marketplace manifest receipt drift detected")
        if catalog_trust["catalog_sha256"] != receipt.get("catalog_sha256"):
            raise MarketplaceTrustError("signed marketplace catalog receipt drift detected")

        evidence = self.marketplace.get_evidence(package_id)
        if evidence.code_sha256 != receipt.get("code_sha256") or evidence.code_sha256 != manifest.code_sha256:
            raise MarketplaceTrustError("signed marketplace code evidence drift detected")
        tool_contract = validate_live_tool_contract(manifest, live_tool_catalog)
        validation = self.marketplace.validate_staged(package_id)
        if not validation.get("valid"):
            return validation
        promoted = self.marketplace.promote(package_id)
        return {
            **promoted,
            "signed_admission_reverified": True,
            "tool_contract": tool_contract,
            "approval_boundary_preserved": True,
        }


__all__ = ["SignedMarketplaceController"]
