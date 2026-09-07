from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from app.capability_forge import CapabilityForge


_PACKAGE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_VERSION_RE = re.compile(r"^10\.0\.[0-9]+(?:[-+][A-Za-z0-9._-]+)?$")
_ALLOWED_RISKS = frozenset({"read", "write", "execute", "external", "destructive"})


class CapabilityMarketplaceError(ValueError):
    """Raised when marketplace evidence fails closed."""


@dataclass(frozen=True)
class MarketplaceManifest:
    package_id: str
    version: str
    publisher_id: str
    source_uri: str
    code_sha256: str
    declared_tools: tuple[str, ...]
    requested_risks: tuple[str, ...]
    minimum_dpn_version: str = "10.0.0"
    maximum_dpn_major: int = 10

    def normalized(self) -> "MarketplaceManifest":
        package_id = self.package_id.strip().lower()
        version = self.version.strip()
        publisher_id = self.publisher_id.strip().lower()
        source_uri = self.source_uri.strip()
        digest = self.code_sha256.strip().lower()
        if not _PACKAGE_ID_RE.fullmatch(package_id):
            raise CapabilityMarketplaceError("invalid marketplace package id")
        if not _VERSION_RE.fullmatch(version):
            raise CapabilityMarketplaceError("marketplace package version must be a 10.0.x checkpoint")
        if not _PACKAGE_ID_RE.fullmatch(publisher_id):
            raise CapabilityMarketplaceError("invalid marketplace publisher id")
        if not source_uri or len(source_uri) > 2048:
            raise CapabilityMarketplaceError("marketplace source URI is required and bounded")
        if not source_uri.startswith(("local://", "repo://", "https://github.com/")):
            raise CapabilityMarketplaceError("marketplace source URI scheme is not trusted")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise CapabilityMarketplaceError("marketplace code sha256 is invalid")
        tools = _bounded_unique(self.declared_tools, "declared tool", 64)
        risks = _bounded_unique(self.requested_risks, "requested risk", 8)
        if any(item not in _ALLOWED_RISKS for item in risks):
            raise CapabilityMarketplaceError("marketplace requested risk is unsupported")
        if self.minimum_dpn_version != "10.0.0" or self.maximum_dpn_major != 10:
            raise CapabilityMarketplaceError("marketplace package is not compatible with the v10 program")
        return MarketplaceManifest(
            package_id=package_id,
            version=version,
            publisher_id=publisher_id,
            source_uri=source_uri,
            code_sha256=digest,
            declared_tools=tools,
            requested_risks=risks,
            minimum_dpn_version="10.0.0",
            maximum_dpn_major=10,
        )


@dataclass(frozen=True)
class MarketplaceEvidence:
    package_id: str
    version: str
    publisher_id: str
    source_uri: str
    code_sha256: str
    manifest_sha256: str
    staged_at: float
    validation_sha256: str | None = None
    promoted_at: float | None = None
    rollback_from: str | None = None


def _bounded_unique(values: Iterable[str], label: str, limit: int) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value).strip().lower()
        if not item:
            raise CapabilityMarketplaceError(f"empty {label} is not allowed")
        if len(item) > 120:
            raise CapabilityMarketplaceError(f"{label} exceeds length bound")
        if item not in seen:
            normalized.append(item)
            seen.add(item)
        if len(normalized) > limit:
            raise CapabilityMarketplaceError(f"too many {label}s")
    return tuple(normalized)


def _canonical_manifest_bytes(manifest: MarketplaceManifest) -> bytes:
    return json.dumps(asdict(manifest), sort_keys=True, separators=(",", ":")).encode("utf-8")


class CapabilityMarketplace:
    """Governed v10 marketplace facade over the existing CapabilityForge.

    Validation never imports or executes package code. Promotion and rollback are
    intended to be registered as high-risk ToolRegistry operations so existing
    ApprovalSecurity remains authoritative.
    """

    def __init__(
        self,
        forge: CapabilityForge,
        data_dir: str | Path,
        *,
        trusted_publishers: Iterable[str] = ("dpn-technology",),
    ) -> None:
        self.forge = forge
        self.state_dir = Path(data_dir).resolve() / "capability_marketplace_v10"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.trusted_publishers = frozenset(_bounded_unique(trusted_publishers, "trusted publisher", 64))
        if not self.trusted_publishers:
            raise CapabilityMarketplaceError("at least one host-trusted publisher is required")

    def _evidence_path(self, package_id: str) -> Path:
        safe = package_id.strip().lower()
        if not _PACKAGE_ID_RE.fullmatch(safe):
            raise CapabilityMarketplaceError("invalid marketplace package id")
        return self.state_dir / f"{safe}.json"

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass

    def inspect_manifest(self, manifest: MarketplaceManifest, code: str) -> dict[str, Any]:
        normalized = manifest.normalized()
        payload = code.encode("utf-8")
        if len(payload) > 1_000_000:
            raise CapabilityMarketplaceError("marketplace package exceeds 1 MB")
        actual_sha = hashlib.sha256(payload).hexdigest()
        if actual_sha != normalized.code_sha256:
            raise CapabilityMarketplaceError("marketplace package digest does not match manifest")
        trusted = normalized.publisher_id in self.trusted_publishers
        compatible = normalized.minimum_dpn_version == "10.0.0" and normalized.maximum_dpn_major == 10
        manifest_sha = hashlib.sha256(_canonical_manifest_bytes(normalized)).hexdigest()
        return {
            "ok": True,
            "trusted_publisher": trusted,
            "compatible": compatible,
            "activatable": bool(trusted and compatible),
            "manifest": asdict(normalized),
            "manifest_sha256": manifest_sha,
            "code_sha256": actual_sha,
            "code_executed": False,
        }

    def stage(self, manifest: MarketplaceManifest, code: str, description: str = "") -> dict[str, Any]:
        inspection = self.inspect_manifest(manifest, code)
        if not inspection["trusted_publisher"]:
            raise CapabilityMarketplaceError("marketplace publisher is not host-trusted")
        if not inspection["compatible"]:
            raise CapabilityMarketplaceError("marketplace package is incompatible")
        normalized = manifest.normalized()
        staged = self.forge.stage(normalized.package_id, code, description=description, overwrite=False)
        if not staged.get("ok"):
            return staged
        evidence = MarketplaceEvidence(
            package_id=normalized.package_id,
            version=normalized.version,
            publisher_id=normalized.publisher_id,
            source_uri=normalized.source_uri,
            code_sha256=normalized.code_sha256,
            manifest_sha256=str(inspection["manifest_sha256"]),
            staged_at=time.time(),
        )
        self._atomic_json(self._evidence_path(normalized.package_id), {"schema_version": 1, "evidence": asdict(evidence)})
        return {**staged, "marketplace": inspection, "execution_authorized": False}

    def validate_staged(self, package_id: str) -> dict[str, Any]:
        evidence = self.get_evidence(package_id)
        validation = self.forge.validate(package_id)
        if not validation.get("valid"):
            return {"ok": False, "valid": False, "validation": validation, "evidence": evidence}
        if validation.get("sha256") != evidence.code_sha256:
            raise CapabilityMarketplaceError("staged package changed after marketplace evidence was recorded")
        updated = MarketplaceEvidence(**{**asdict(evidence), "validation_sha256": str(validation["sha256"])})
        self._atomic_json(self._evidence_path(package_id), {"schema_version": 1, "evidence": asdict(updated)})
        return {"ok": True, "valid": True, "validation": validation, "evidence": asdict(updated), "execution_authorized": False}

    def promote(self, package_id: str) -> dict[str, Any]:
        evidence = self.get_evidence(package_id)
        validation = self.validate_staged(package_id)
        if not validation.get("valid"):
            return validation
        promoted = self.forge.promote(package_id)
        if not promoted.get("ok"):
            return promoted
        updated = MarketplaceEvidence(**{**asdict(evidence), "validation_sha256": evidence.code_sha256, "promoted_at": time.time()})
        self._atomic_json(self._evidence_path(package_id), {"schema_version": 1, "evidence": asdict(updated)})
        return {**promoted, "marketplace_evidence": asdict(updated), "approval_boundary_preserved": True}

    def rollback(self, package_id: str, backup_name: str | None = None) -> dict[str, Any]:
        evidence = self.get_evidence(package_id)
        result = self.forge.rollback(package_id, backup_name=backup_name)
        if not result.get("ok"):
            return result
        updated = MarketplaceEvidence(**{**asdict(evidence), "rollback_from": str(result.get("restored_from") or "")})
        self._atomic_json(self._evidence_path(package_id), {"schema_version": 1, "evidence": asdict(updated)})
        return {**result, "marketplace_evidence": asdict(updated), "approval_boundary_preserved": True}

    def get_evidence(self, package_id: str) -> MarketplaceEvidence:
        path = self._evidence_path(package_id)
        if not path.is_file() or path.is_symlink():
            raise CapabilityMarketplaceError("marketplace evidence is missing")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != 1 or not isinstance(payload.get("evidence"), dict):
                raise ValueError("invalid schema")
            evidence = MarketplaceEvidence(**payload["evidence"])
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CapabilityMarketplaceError("marketplace evidence is corrupt") from exc
        if evidence.publisher_id not in self.trusted_publishers:
            raise CapabilityMarketplaceError("marketplace publisher trust has been revoked")
        return evidence

    def list_packages(self) -> dict[str, Any]:
        packages: list[dict[str, Any]] = []
        for path in sorted(self.state_dir.glob("*.json")):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                evidence = self.get_evidence(path.stem)
                packages.append(asdict(evidence))
            except CapabilityMarketplaceError:
                packages.append({"package_id": path.stem, "status": "invalid-evidence"})
        return {"ok": True, "count": len(packages), "packages": packages}


__all__ = [
    "CapabilityMarketplace",
    "CapabilityMarketplaceError",
    "MarketplaceEvidence",
    "MarketplaceManifest",
]
