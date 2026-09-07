from __future__ import annotations

import base64
import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.capability_marketplace_v10 import (
    CapabilityMarketplace,
    CapabilityMarketplaceError,
    MarketplaceManifest,
    _canonical_manifest_bytes,
)


class MarketplaceTrustError(CapabilityMarketplaceError):
    """Raised when signed marketplace trust evidence fails closed."""


@dataclass(frozen=True)
class PublisherKey:
    publisher_id: str
    key_id: str
    public_key_b64: str
    revoked: bool = False

    def normalized(self) -> "PublisherKey":
        publisher = self.publisher_id.strip().lower()
        key_id = self.key_id.strip().lower()
        if not publisher or len(publisher) > 80:
            raise MarketplaceTrustError("invalid publisher identity")
        if not key_id or len(key_id) > 120:
            raise MarketplaceTrustError("invalid publisher key id")
        try:
            raw = base64.b64decode(self.public_key_b64, validate=True)
        except Exception as exc:
            raise MarketplaceTrustError("publisher public key is not valid base64") from exc
        if len(raw) != 32:
            raise MarketplaceTrustError("publisher public key must be Ed25519")
        return PublisherKey(publisher, key_id, base64.b64encode(raw).decode("ascii"), bool(self.revoked))

    def public_key(self) -> Ed25519PublicKey:
        normalized = self.normalized()
        return Ed25519PublicKey.from_public_bytes(base64.b64decode(normalized.public_key_b64))


@dataclass(frozen=True)
class PackageSignature:
    publisher_id: str
    key_id: str
    signature_b64: str


@dataclass(frozen=True)
class CatalogEntry:
    package_id: str
    version: str
    manifest_sha256: str

    def normalized(self) -> "CatalogEntry":
        package_id = self.package_id.strip().lower()
        version = self.version.strip()
        digest = self.manifest_sha256.strip().lower()
        if not package_id or len(package_id) > 80:
            raise MarketplaceTrustError("invalid catalog package id")
        if not version.startswith("10.0.") or len(version) > 80:
            raise MarketplaceTrustError("catalog entry must reference a v10 checkpoint")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise MarketplaceTrustError("invalid catalog manifest digest")
        return CatalogEntry(package_id, version, digest)


@dataclass(frozen=True)
class SignedCatalog:
    publisher_id: str
    key_id: str
    generated_at: float
    expires_at: float
    entries: tuple[CatalogEntry, ...]
    signature_b64: str
    schema_version: int = 1


class PublisherTrustStore:
    """Host-owned public-key trust store. Model/package data cannot add trust roots."""

    def __init__(self, keys: Iterable[PublisherKey]) -> None:
        normalized = [item.normalized() for item in keys]
        if not normalized:
            raise MarketplaceTrustError("at least one publisher public key is required")
        self._keys: dict[tuple[str, str], PublisherKey] = {}
        for item in normalized:
            key = (item.publisher_id, item.key_id)
            if key in self._keys:
                raise MarketplaceTrustError("duplicate publisher key id")
            self._keys[key] = item

    def resolve(self, publisher_id: str, key_id: str) -> PublisherKey:
        key = self._keys.get((publisher_id.strip().lower(), key_id.strip().lower()))
        if key is None:
            raise MarketplaceTrustError("publisher signing key is not host-trusted")
        if key.revoked:
            raise MarketplaceTrustError("publisher signing key has been revoked")
        return key


def _decode_signature(value: str) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise MarketplaceTrustError("signature is not valid base64") from exc
    if len(raw) != 64:
        raise MarketplaceTrustError("signature must be Ed25519")
    return raw


def _verify(key: PublisherKey, signature_b64: str, payload: bytes) -> None:
    try:
        key.public_key().verify(_decode_signature(signature_b64), payload)
    except InvalidSignature as exc:
        raise MarketplaceTrustError("marketplace signature verification failed") from exc


def canonical_catalog_bytes(catalog: SignedCatalog) -> bytes:
    entries = [asdict(entry.normalized()) for entry in catalog.entries]
    payload = {
        "schema_version": int(catalog.schema_version),
        "publisher_id": catalog.publisher_id.strip().lower(),
        "key_id": catalog.key_id.strip().lower(),
        "generated_at": float(catalog.generated_at),
        "expires_at": float(catalog.expires_at),
        "entries": entries,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


class MarketplaceTrustVerifier:
    MAX_CATALOG_ENTRIES = 1024
    MAX_CATALOG_LIFETIME_SECONDS = 7 * 24 * 60 * 60
    MAX_FUTURE_SKEW_SECONDS = 300

    def __init__(self, trust_store: PublisherTrustStore) -> None:
        self.trust_store = trust_store

    def verify_package(self, manifest: MarketplaceManifest, signature: PackageSignature) -> dict[str, Any]:
        normalized = manifest.normalized()
        if signature.publisher_id.strip().lower() != normalized.publisher_id:
            raise MarketplaceTrustError("package signature publisher does not match manifest")
        key = self.trust_store.resolve(signature.publisher_id, signature.key_id)
        _verify(key, signature.signature_b64, _canonical_manifest_bytes(normalized))
        manifest_sha = hashlib.sha256(_canonical_manifest_bytes(normalized)).hexdigest()
        return {
            "ok": True,
            "publisher_id": normalized.publisher_id,
            "key_id": key.key_id,
            "manifest_sha256": manifest_sha,
            "signature_verified": True,
        }

    def verify_catalog(self, catalog: SignedCatalog, *, now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        if not math.isfinite(current):
            raise MarketplaceTrustError("catalog verification time must be finite")
        if catalog.schema_version != 1:
            raise MarketplaceTrustError("unsupported marketplace catalog schema")
        if not math.isfinite(catalog.generated_at) or not math.isfinite(catalog.expires_at):
            raise MarketplaceTrustError("catalog timestamps must be finite")
        if catalog.generated_at > current + self.MAX_FUTURE_SKEW_SECONDS:
            raise MarketplaceTrustError("catalog was generated too far in the future")
        if catalog.expires_at <= current:
            raise MarketplaceTrustError("marketplace catalog is expired")
        lifetime = catalog.expires_at - catalog.generated_at
        if lifetime <= 0 or lifetime > self.MAX_CATALOG_LIFETIME_SECONDS:
            raise MarketplaceTrustError("marketplace catalog lifetime is outside policy")
        if not catalog.entries or len(catalog.entries) > self.MAX_CATALOG_ENTRIES:
            raise MarketplaceTrustError("marketplace catalog entry count is outside policy")
        normalized_entries = tuple(entry.normalized() for entry in catalog.entries)
        identities = [(entry.package_id, entry.version) for entry in normalized_entries]
        if len(set(identities)) != len(identities):
            raise MarketplaceTrustError("marketplace catalog contains duplicate package versions")
        key = self.trust_store.resolve(catalog.publisher_id, catalog.key_id)
        _verify(key, catalog.signature_b64, canonical_catalog_bytes(catalog))
        digest = hashlib.sha256(canonical_catalog_bytes(catalog)).hexdigest()
        return {
            "ok": True,
            "publisher_id": key.publisher_id,
            "key_id": key.key_id,
            "catalog_sha256": digest,
            "entry_count": len(normalized_entries),
            "expires_at": catalog.expires_at,
            "signature_verified": True,
        }

    def verify_catalog_membership(
        self,
        manifest: MarketplaceManifest,
        catalog: SignedCatalog,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        catalog_result = self.verify_catalog(catalog, now=now)
        normalized = manifest.normalized()
        if normalized.publisher_id != catalog.publisher_id.strip().lower():
            raise MarketplaceTrustError("catalog publisher does not match package publisher")
        manifest_sha = hashlib.sha256(_canonical_manifest_bytes(normalized)).hexdigest()
        matches = [
            entry.normalized()
            for entry in catalog.entries
            if entry.package_id.strip().lower() == normalized.package_id and entry.version.strip() == normalized.version
        ]
        if len(matches) != 1 or matches[0].manifest_sha256 != manifest_sha:
            raise MarketplaceTrustError("package manifest is not bound to signed catalog")
        return {**catalog_result, "manifest_sha256": manifest_sha, "catalog_member": True}


def validate_live_tool_contract(manifest: MarketplaceManifest, live_catalog: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    normalized = manifest.normalized()
    if not isinstance(live_catalog, Sequence) or isinstance(live_catalog, (str, bytes)):
        raise MarketplaceTrustError("live ToolRegistry catalog is unavailable")
    by_name: dict[str, Mapping[str, Any]] = {}
    for item in live_catalog:
        if not isinstance(item, Mapping):
            raise MarketplaceTrustError("live ToolRegistry catalog is malformed")
        name = str(item.get("name") or "").strip().lower()
        risk = str(item.get("risk") or "").strip().lower()
        if not name or risk not in {"read", "write", "execute", "external", "destructive"}:
            raise MarketplaceTrustError("live ToolRegistry catalog contains invalid metadata")
        if name in by_name:
            raise MarketplaceTrustError("live ToolRegistry catalog contains duplicate tool names")
        by_name[name] = item
    missing = tuple(sorted(name for name in normalized.declared_tools if name not in by_name))
    if missing:
        raise MarketplaceTrustError("marketplace package references unavailable ToolRegistry tools")
    observed_risks = tuple(sorted({str(by_name[name].get("risk") or "").strip().lower() for name in normalized.declared_tools}))
    undeclared_risks = tuple(sorted(set(observed_risks).difference(normalized.requested_risks)))
    if undeclared_risks:
        raise MarketplaceTrustError("live ToolRegistry risk exceeds package declaration")
    return {
        "ok": True,
        "declared_tools": normalized.declared_tools,
        "observed_risks": observed_risks,
        "missing_tools": (),
        "risk_contract_verified": True,
        "execution_authorized": False,
    }


class SignedMarketplaceStager:
    """Non-executing signed staging bridge over CapabilityMarketplace."""

    def __init__(self, marketplace: CapabilityMarketplace, verifier: MarketplaceTrustVerifier) -> None:
        self.marketplace = marketplace
        self.verifier = verifier

    def stage_verified(
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
        return {
            **staged,
            "package_signature": package_trust,
            "catalog_signature": catalog_trust,
            "tool_contract": tool_contract,
            "execution_authorized": False,
        }


__all__ = [
    "CatalogEntry",
    "MarketplaceTrustError",
    "MarketplaceTrustVerifier",
    "PackageSignature",
    "PublisherKey",
    "PublisherTrustStore",
    "SignedCatalog",
    "SignedMarketplaceStager",
    "canonical_catalog_bytes",
    "validate_live_tool_contract",
]
