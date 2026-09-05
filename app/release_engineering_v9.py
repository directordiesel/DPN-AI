from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping


class ReleaseEngineeringError(ValueError):
    pass


class ReleaseChannel(str, Enum):
    STABLE = "stable"
    BETA = "beta"
    RC = "rc"


_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-rc\.\d+)?$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ReleaseArtifact:
    name: str
    size_bytes: int
    sha256: str
    required: bool = True

    def validate(self) -> None:
        if not self.name or "/" in self.name or "\\" in self.name:
            raise ReleaseEngineeringError("artifact name must be a basename")
        if self.size_bytes <= 0:
            raise ReleaseEngineeringError("artifact size must be positive")
        if not _SHA_RE.fullmatch(self.sha256):
            raise ReleaseEngineeringError("artifact sha256 must be a lowercase 64-character digest")


@dataclass(frozen=True)
class ReleaseCandidate:
    version: str
    channel: ReleaseChannel
    commit_sha: str
    artifacts: tuple[ReleaseArtifact, ...]
    installer_verified: bool
    rollback_verified: bool
    version_sources: Mapping[str, str]
    evaluation_passed: bool
    ci_passed: bool
    security_passed: bool
    recovery_passed: bool


@dataclass(frozen=True)
class ReleaseDecision:
    ready: bool
    reasons: tuple[str, ...]
    manifest_digest: str


class ReleaseEngineeringGate:
    """Fail-closed v9 release-candidate validation.

    This gate does not publish a release. It validates installer/package evidence,
    version coherence, required artifacts, rollback readiness, and exact-head
    quality signals before a later release workflow is allowed to proceed.
    """

    REQUIRED_ARTIFACTS = {
        "SBOM.spdx.json",
        "SHA256SUMS.txt",
        "RELEASE_MANIFEST.txt",
    }

    @staticmethod
    def _validate_version(version: str, channel: ReleaseChannel) -> None:
        value = str(version or "").strip()
        if not _VERSION_RE.fullmatch(value):
            raise ReleaseEngineeringError("version must use semantic versioning")
        is_rc = "-rc." in value
        if channel == ReleaseChannel.RC and not is_rc:
            raise ReleaseEngineeringError("RC channel requires an -rc.N version")
        if channel != ReleaseChannel.RC and is_rc:
            raise ReleaseEngineeringError("non-RC channel cannot use an RC version")

    @staticmethod
    def _manifest_digest(candidate: ReleaseCandidate) -> str:
        parts = [candidate.version, candidate.channel.value, candidate.commit_sha]
        for artifact in sorted(candidate.artifacts, key=lambda item: item.name):
            parts.extend([artifact.name, str(artifact.size_bytes), artifact.sha256])
        for key, value in sorted(candidate.version_sources.items()):
            parts.extend([key, value])
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()

    @classmethod
    def evaluate(cls, candidate: ReleaseCandidate) -> ReleaseDecision:
        cls._validate_version(candidate.version, candidate.channel)
        reasons: list[str] = []

        if not re.fullmatch(r"[0-9a-f]{40}", candidate.commit_sha):
            reasons.append("release commit SHA must be an exact 40-character lowercase Git SHA")

        artifact_names: set[str] = set()
        for artifact in candidate.artifacts:
            artifact.validate()
            if artifact.name in artifact_names:
                reasons.append(f"duplicate artifact: {artifact.name}")
            artifact_names.add(artifact.name)

        missing = sorted(cls.REQUIRED_ARTIFACTS - artifact_names)
        if missing:
            reasons.append("missing required release artifacts: " + ", ".join(missing))

        for source, value in sorted(candidate.version_sources.items()):
            if str(value).strip() != candidate.version:
                reasons.append(f"version mismatch in {source}")

        if not candidate.version_sources:
            reasons.append("no version-source evidence supplied")
        if not candidate.installer_verified:
            reasons.append("installer/package verification is not complete")
        if not candidate.rollback_verified:
            reasons.append("rollback/recovery verification is not complete")
        if not candidate.evaluation_passed:
            reasons.append("v9 production evaluation gate is not green")
        if not candidate.ci_passed:
            reasons.append("CI is not green")
        if not candidate.security_passed:
            reasons.append("security gate is not green")
        if not candidate.recovery_passed:
            reasons.append("runtime/recovery assurance is not green")

        return ReleaseDecision(
            ready=not reasons,
            reasons=tuple(reasons),
            manifest_digest=cls._manifest_digest(candidate),
        )

    @staticmethod
    def verify_checksum(*, payload: bytes, expected_sha256: str) -> bool:
        if not _SHA_RE.fullmatch(str(expected_sha256 or "")):
            return False
        actual = hashlib.sha256(payload).hexdigest()
        return hmac.compare_digest(actual, expected_sha256)


__all__ = [
    "ReleaseArtifact",
    "ReleaseCandidate",
    "ReleaseChannel",
    "ReleaseDecision",
    "ReleaseEngineeringError",
    "ReleaseEngineeringGate",
]
