from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import asdict

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.capability_marketplace_v10 import MarketplaceManifest
from app.marketplace_trust_v10 import (
    CatalogEntry,
    MarketplaceTrustError,
    MarketplaceTrustVerifier,
    PackageSignature,
    PublisherKey,
    PublisherTrustStore,
    SignedCatalog,
    canonical_catalog_bytes,
    validate_live_tool_contract,
)


def _keypair(*, revoked=False):
    private = Ed25519PrivateKey.generate()
    public_raw = private.public_key().public_bytes_raw()
    key = PublisherKey(
        publisher_id="dpn-technology",
        key_id="release-key-1",
        public_key_b64=base64.b64encode(public_raw).decode("ascii"),
        revoked=revoked,
    )
    return private, key


def _manifest(code="def register(registry):\n    return True\n"):
    return MarketplaceManifest(
        package_id="dpn.safe-tool",
        version="10.0.13",
        publisher_id="dpn-technology",
        source_uri="repo://dpn.safe-tool",
        code_sha256=hashlib.sha256(code.encode()).hexdigest(),
        declared_tools=("search_docs",),
        requested_risks=("read",),
    )


def _manifest_bytes(manifest):
    normalized = manifest.normalized()
    return json.dumps(asdict(normalized), sort_keys=True, separators=(",", ":")).encode()


def _package_signature(private, manifest):
    signature = private.sign(_manifest_bytes(manifest))
    return PackageSignature(
        publisher_id="dpn-technology",
        key_id="release-key-1",
        signature_b64=base64.b64encode(signature).decode("ascii"),
    )


def _catalog(private, manifest, *, now=1000.0, expires=2000.0):
    digest = hashlib.sha256(_manifest_bytes(manifest)).hexdigest()
    unsigned = SignedCatalog(
        publisher_id="dpn-technology",
        key_id="release-key-1",
        generated_at=now,
        expires_at=expires,
        entries=(CatalogEntry(manifest.package_id, manifest.version, digest),),
        signature_b64="",
    )
    signature = private.sign(canonical_catalog_bytes(unsigned))
    return SignedCatalog(**{**asdict(unsigned), "entries": unsigned.entries, "signature_b64": base64.b64encode(signature).decode("ascii")})


def test_package_signature_and_catalog_membership_are_verified():
    private, key = _keypair()
    manifest = _manifest()
    verifier = MarketplaceTrustVerifier(PublisherTrustStore([key]))

    package = verifier.verify_package(manifest, _package_signature(private, manifest))
    membership = verifier.verify_catalog_membership(manifest, _catalog(private, manifest), now=1500.0)

    assert package["signature_verified"] is True
    assert membership["signature_verified"] is True
    assert membership["catalog_member"] is True
    assert membership["manifest_sha256"] == package["manifest_sha256"]


def test_tampered_manifest_fails_detached_signature_verification():
    private, key = _keypair()
    original = _manifest()
    tampered = MarketplaceManifest(**{**asdict(original), "version": "10.0.14"})
    verifier = MarketplaceTrustVerifier(PublisherTrustStore([key]))

    with pytest.raises(MarketplaceTrustError, match="signature verification failed"):
        verifier.verify_package(tampered, _package_signature(private, original))


def test_revoked_host_key_fails_closed():
    private, key = _keypair(revoked=True)
    manifest = _manifest()
    verifier = MarketplaceTrustVerifier(PublisherTrustStore([key]))

    with pytest.raises(MarketplaceTrustError, match="revoked"):
        verifier.verify_package(manifest, _package_signature(private, manifest))


def test_expired_catalog_and_duplicate_versions_fail_closed():
    private, key = _keypair()
    manifest = _manifest()
    verifier = MarketplaceTrustVerifier(PublisherTrustStore([key]))

    expired = _catalog(private, manifest, now=1000.0, expires=1100.0)
    with pytest.raises(MarketplaceTrustError, match="expired"):
        verifier.verify_catalog(expired, now=1200.0)

    digest = hashlib.sha256(_manifest_bytes(manifest)).hexdigest()
    unsigned = SignedCatalog(
        publisher_id="dpn-technology",
        key_id="release-key-1",
        generated_at=1000.0,
        expires_at=2000.0,
        entries=(CatalogEntry(manifest.package_id, manifest.version, digest), CatalogEntry(manifest.package_id, manifest.version, digest)),
        signature_b64="",
    )
    signed = SignedCatalog(**{**asdict(unsigned), "entries": unsigned.entries, "signature_b64": base64.b64encode(private.sign(canonical_catalog_bytes(unsigned))).decode("ascii")})
    with pytest.raises(MarketplaceTrustError, match="duplicate"):
        verifier.verify_catalog(signed, now=1500.0)


def test_live_tool_contract_rejects_missing_tools_and_risk_escalation():
    manifest = _manifest()

    with pytest.raises(MarketplaceTrustError, match="unavailable"):
        validate_live_tool_contract(manifest, [{"name": "other", "risk": "read"}])

    with pytest.raises(MarketplaceTrustError, match="risk exceeds"):
        validate_live_tool_contract(manifest, [{"name": "search_docs", "risk": "external"}])


def test_live_tool_contract_is_non_authorizing_when_exact():
    result = validate_live_tool_contract(
        _manifest(),
        [{"name": "search_docs", "risk": "read", "gate": "files"}],
    )
    assert result["ok"] is True
    assert result["risk_contract_verified"] is True
    assert result["execution_authorized"] is False
