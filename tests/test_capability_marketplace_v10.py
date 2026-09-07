from __future__ import annotations

import hashlib

import pytest

from app.capability_forge import CapabilityForge
from app.capability_marketplace_v10 import (
    CapabilityMarketplace,
    CapabilityMarketplaceError,
    MarketplaceManifest,
)


GOOD_CODE = "def register(registry):\n    return None\n"


def _manifest(*, publisher="dpn-technology", code=GOOD_CODE, package_id="verified_plugin"):
    return MarketplaceManifest(
        package_id=package_id,
        version="10.0.13",
        publisher_id=publisher,
        source_uri="repo://directordiesel/DPN-AI/verified_plugin",
        code_sha256=hashlib.sha256(code.encode("utf-8")).hexdigest(),
        declared_tools=("verified_tool",),
        requested_risks=("read",),
    )


def _marketplace(tmp_path):
    forge = CapabilityForge(tmp_path / "plugins", tmp_path / "data")
    return forge, CapabilityMarketplace(forge, tmp_path / "data")


def test_marketplace_inspection_is_digest_bound_and_never_executes_code(tmp_path):
    _, marketplace = _marketplace(tmp_path)
    result = marketplace.inspect_manifest(_manifest(), GOOD_CODE)
    assert result["ok"] is True
    assert result["trusted_publisher"] is True
    assert result["compatible"] is True
    assert result["activatable"] is True
    assert result["code_executed"] is False
    assert result["code_sha256"] == hashlib.sha256(GOOD_CODE.encode()).hexdigest()


def test_marketplace_rejects_digest_mismatch_and_untrusted_publisher(tmp_path):
    _, marketplace = _marketplace(tmp_path)
    with pytest.raises(CapabilityMarketplaceError, match="digest"):
        marketplace.inspect_manifest(_manifest(), GOOD_CODE + "# changed\n")
    with pytest.raises(CapabilityMarketplaceError, match="host-trusted"):
        marketplace.stage(_manifest(publisher="unknown-publisher"), GOOD_CODE)


def test_marketplace_stages_then_revalidates_without_activation(tmp_path):
    forge, marketplace = _marketplace(tmp_path)
    staged = marketplace.stage(_manifest(), GOOD_CODE, "Verified test package")
    assert staged["ok"] is True
    assert staged["execution_authorized"] is False
    assert (forge.staging_dir / "verified_plugin" / "verified_plugin.py").is_file()
    assert not (forge.plugins_dir / "verified_plugin.py").exists()

    validation = marketplace.validate_staged("verified_plugin")
    assert validation["ok"] is True
    assert validation["valid"] is True
    assert validation["execution_authorized"] is False
    assert not (forge.plugins_dir / "verified_plugin.py").exists()


def test_marketplace_detects_staged_code_drift(tmp_path):
    forge, marketplace = _marketplace(tmp_path)
    marketplace.stage(_manifest(), GOOD_CODE)
    staged_path = forge.staging_dir / "verified_plugin" / "verified_plugin.py"
    staged_path.write_text(GOOD_CODE + "# drift\n", encoding="utf-8")
    with pytest.raises(CapabilityMarketplaceError, match="changed"):
        marketplace.validate_staged("verified_plugin")


def test_marketplace_promotion_uses_forge_and_preserves_evidence(tmp_path):
    forge, marketplace = _marketplace(tmp_path)
    marketplace.stage(_manifest(), GOOD_CODE)
    result = marketplace.promote("verified_plugin")
    assert result["ok"] is True
    assert result["approval_boundary_preserved"] is True
    assert result["restart_required"] is True
    assert (forge.plugins_dir / "verified_plugin.py").read_text(encoding="utf-8") == GOOD_CODE
    evidence = marketplace.get_evidence("verified_plugin")
    assert evidence.promoted_at is not None
    assert evidence.validation_sha256 == evidence.code_sha256


def test_marketplace_trust_revocation_blocks_persisted_evidence(tmp_path):
    forge, marketplace = _marketplace(tmp_path)
    marketplace.stage(_manifest(), GOOD_CODE)
    revoked = CapabilityMarketplace(forge, tmp_path / "data", trusted_publishers=("different-publisher",))
    with pytest.raises(CapabilityMarketplaceError, match="revoked"):
        revoked.get_evidence("verified_plugin")


def test_marketplace_manifest_is_restricted_to_v10_checkpoint_versions(tmp_path):
    _, marketplace = _marketplace(tmp_path)
    manifest = _manifest()
    incompatible = MarketplaceManifest(**{**manifest.__dict__, "version": "11.0.0"})
    with pytest.raises(CapabilityMarketplaceError, match="10.0.x"):
        marketplace.inspect_manifest(incompatible, GOOD_CODE)
