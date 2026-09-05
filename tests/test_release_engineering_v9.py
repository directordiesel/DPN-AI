import hashlib

import pytest

from app.release_engineering_v9 import (
    ReleaseArtifact,
    ReleaseCandidate,
    ReleaseChannel,
    ReleaseEngineeringError,
    ReleaseEngineeringGate,
)


def artifact(name: str) -> ReleaseArtifact:
    payload = name.encode("utf-8")
    return ReleaseArtifact(name=name, size_bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())


def ready_candidate(**overrides):
    data = {
        "version": "9.0.0-rc.1",
        "channel": ReleaseChannel.RC,
        "commit_sha": "a" * 40,
        "artifacts": (
            artifact("SBOM.spdx.json"),
            artifact("SHA256SUMS.txt"),
            artifact("RELEASE_MANIFEST.txt"),
            artifact("DPN-AI-v9.0.0-rc.1-source.zip"),
        ),
        "installer_verified": True,
        "rollback_verified": True,
        "version_sources": {"VERSION": "9.0.0-rc.1", "desktop": "9.0.0-rc.1", "mobile": "9.0.0-rc.1"},
        "evaluation_passed": True,
        "ci_passed": True,
        "security_passed": True,
        "recovery_passed": True,
    }
    data.update(overrides)
    return ReleaseCandidate(**data)


def test_ready_release_candidate_passes():
    decision = ReleaseEngineeringGate.evaluate(ready_candidate())
    assert decision.ready is True
    assert decision.reasons == ()
    assert len(decision.manifest_digest) == 64


def test_missing_required_artifact_blocks_release():
    candidate = ready_candidate(artifacts=(artifact("SBOM.spdx.json"), artifact("SHA256SUMS.txt")))
    decision = ReleaseEngineeringGate.evaluate(candidate)
    assert decision.ready is False
    assert any("RELEASE_MANIFEST.txt" in reason for reason in decision.reasons)


def test_version_mismatch_blocks_release():
    candidate = ready_candidate(version_sources={"VERSION": "9.0.0-rc.1", "mobile": "8.0.0"})
    decision = ReleaseEngineeringGate.evaluate(candidate)
    assert decision.ready is False
    assert "version mismatch in mobile" in decision.reasons


def test_quality_gate_failure_blocks_release():
    decision = ReleaseEngineeringGate.evaluate(ready_candidate(security_passed=False))
    assert decision.ready is False
    assert "security gate is not green" in decision.reasons


def test_rc_channel_requires_rc_version():
    with pytest.raises(ReleaseEngineeringError):
        ReleaseEngineeringGate.evaluate(ready_candidate(version="9.0.0"))


def test_checksum_verification_is_exact():
    payload = b"release artifact"
    digest = hashlib.sha256(payload).hexdigest()
    assert ReleaseEngineeringGate.verify_checksum(payload=payload, expected_sha256=digest) is True
    assert ReleaseEngineeringGate.verify_checksum(payload=payload + b"x", expected_sha256=digest) is False
