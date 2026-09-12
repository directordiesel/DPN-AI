"""Secure DPN AI desktop release discovery and verified download client.

Production builds package only the public Ed25519 update-verification key. The
private signing key never enters the application. Update discovery is restricted
to the official DPN-AI GitHub repository, every update manifest must verify
against the packaged key, and installers are streamed to disk with signed
size/SHA-256 enforcement before they are exposed to the desktop runtime.

This module never executes an installer.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from desktop.updater import (
    UPDATE_KEY_ID,
    UPDATE_REPOSITORY,
    SignedUpdateManifest,
    validate_manifest_trust_binding,
    verify_artifact,
    verify_manifest_signature,
)


UPDATE_API_URL = f"https://api.github.com/repos/{UPDATE_REPOSITORY}/releases?per_page=20"
UPDATE_TRUST_FILENAME = "update-trust.json"
UPDATE_USER_AGENT = "DPN-AI-Secure-Updater/1"
MAX_RELEASE_METADATA_BYTES = 2 * 1024 * 1024
MAX_UPDATE_MANIFEST_BYTES = 128 * 1024
MAX_REDIRECTS = 5
_ALLOWED_CHANNELS = {"stable", "beta"}
_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?$"
)
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class UpdateClientError(RuntimeError):
    """Raised when remote update state cannot be trusted or safely processed."""


@dataclass(frozen=True)
class UpdateTrustRoot:
    repository: str
    key_id: str
    public_key: bytes
    public_key_sha256: str

    @classmethod
    def parse(cls, raw: str) -> "UpdateTrustRoot":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise UpdateClientError("update trust root is not valid JSON") from exc
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise UpdateClientError("update trust root schema is invalid")
        repository = str(data.get("repository") or "").strip()
        if repository != UPDATE_REPOSITORY:
            raise UpdateClientError("update trust root repository is not authorized")
        key_id = str(data.get("key_id") or "").strip()
        if _KEY_ID_RE.fullmatch(key_id) is None or key_id != UPDATE_KEY_ID:
            raise UpdateClientError("update trust root key id is not authorized")
        public_hex = str(data.get("ed25519_public_key_hex") or "").strip().lower()
        if len(public_hex) != 64 or any(ch not in "0123456789abcdef" for ch in public_hex):
            raise UpdateClientError("update trust root public key is invalid")
        public_key = bytes.fromhex(public_hex)
        expected_fingerprint = hashlib.sha256(public_key).hexdigest()
        supplied_fingerprint = str(data.get("public_key_sha256") or "").strip().lower()
        if supplied_fingerprint and not hmac.compare_digest(supplied_fingerprint, expected_fingerprint):
            raise UpdateClientError("update trust root fingerprint does not match public key")
        return cls(
            repository=repository,
            key_id=key_id,
            public_key=public_key,
            public_key_sha256=expected_fingerprint,
        )


@dataclass(frozen=True)
class UpdateCandidate:
    release_tag: str
    release_url: str
    manifest: SignedUpdateManifest
    installer_url: str
    manifest_url: str

    def safe_summary(self) -> dict[str, Any]:
        artifact = self.manifest.artifact
        return {
            "available": True,
            "version": artifact.version,
            "channel": artifact.channel,
            "filename": artifact.filename,
            "sha256": artifact.sha256,
            "size": artifact.size,
            "release_tag": self.release_tag,
            "release_url": self.release_url,
        }


@dataclass(frozen=True)
class VerifiedUpdateDownload:
    path: Path
    version: str
    channel: str
    sha256: str
    size: int
    authenticode_verified: bool

    def safe_summary(self) -> dict[str, Any]:
        return {
            "verified": True,
            "filename": self.path.name,
            "version": self.version,
            "channel": self.channel,
            "sha256": self.sha256,
            "size": self.size,
            "authenticode_verified": self.authenticode_verified,
        }


def packaged_update_trust_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base / "desktop" / UPDATE_TRUST_FILENAME


def load_packaged_update_trust_root(path: Path | None = None) -> UpdateTrustRoot:
    target = Path(path) if path is not None else packaged_update_trust_path()
    if target.is_symlink():
        raise UpdateClientError("update trust root must not be a symlink")
    if not target.is_file():
        raise UpdateClientError("this build does not contain a production update trust root")
    if target.stat().st_size > 16 * 1024:
        raise UpdateClientError("update trust root is unexpectedly large")
    return UpdateTrustRoot.parse(target.read_text(encoding="utf-8"))


def _semver_key(version: str) -> tuple[int, int, int, int, tuple[tuple[int, int | str], ...]]:
    match = _SEMVER_RE.fullmatch(str(version or "").strip())
    if match is None:
        raise UpdateClientError(f"invalid semantic version: {version!r}")
    prerelease = match.group("pre")
    if prerelease is None:
        pre_key: tuple[tuple[int, int | str], ...] = ()
        stable_rank = 1
    else:
        identifiers: list[tuple[int, int | str]] = []
        for item in prerelease.split("."):
            if not item:
                raise UpdateClientError("invalid empty prerelease identifier")
            identifiers.append((0, int(item)) if item.isdigit() else (1, item.lower()))
        pre_key = tuple(identifiers)
        stable_rank = 0
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        stable_rank,
        pre_key,
    )


def _validate_remote_url(url: str, *, initial_asset: bool = False) -> str:
    value = str(url or "").strip()
    try:
        parsed = urlparse(value)
    except ValueError as exc:
        raise UpdateClientError("update URL is invalid") from exc
    host = str(parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise UpdateClientError("update transport must use credential-free HTTPS")
    if parsed.port not in (None, 443):
        raise UpdateClientError("update URL uses an unexpected port")
    allowed_host = (
        host in {"api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
        or host.endswith(".githubusercontent.com")
    )
    if not allowed_host:
        raise UpdateClientError("update URL host is not in the GitHub allowlist")
    if initial_asset:
        expected_prefix = f"/{UPDATE_REPOSITORY}/releases/download/"
        if host != "github.com" or not parsed.path.startswith(expected_prefix):
            raise UpdateClientError("release asset URL is not owned by the official DPN-AI repository")
    return value


def _desktop_update_root() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "DPN Technology" / "DPN AI" / "updates"
    return Path.home() / ".local" / "share" / "DPN Technology" / "DPN AI" / "updates"


def verify_windows_authenticode(path: Path) -> bool:
    """Require a valid Windows Authenticode signature without shell interpolation."""
    if sys.platform != "win32":
        return False
    env = dict(os.environ)
    env["DPN_UPDATE_VERIFY_PATH"] = str(path)
    script = (
        "$s = Get-AuthenticodeSignature -LiteralPath $env:DPN_UPDATE_VERIFY_PATH; "
        "if ($s.Status -ne [System.Management.Automation.SignatureStatus]::Valid) { exit 3 }; "
        "if (-not $s.SignerCertificate) { exit 4 }; "
        "Write-Output $s.SignerCertificate.Thumbprint"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=env,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


class GitHubReleaseUpdateClient:
    def __init__(
        self,
        trust_root: UpdateTrustRoot,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if trust_root.repository != UPDATE_REPOSITORY:
            raise UpdateClientError("untrusted update repository")
        self.trust_root = trust_root
        self.timeout = float(timeout)
        self.transport = transport

    async def _fetch_bytes(
        self,
        url: str,
        *,
        max_bytes: int,
        initial_asset: bool = False,
        accept: str = "application/octet-stream",
    ) -> bytes:
        current = _validate_remote_url(url, initial_asset=initial_asset)
        headers = {"Accept": accept, "User-Agent": UPDATE_USER_AGENT}
        async with httpx.AsyncClient(
            trust_env=False,
            timeout=self.timeout,
            follow_redirects=False,
            transport=self.transport,
            headers=headers,
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                async with client.stream("GET", current) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("Location", "")
                        if not location:
                            raise UpdateClientError("GitHub update redirect omitted Location")
                        current = _validate_remote_url(urljoin(current, location))
                        continue
                    if response.status_code != 200:
                        raise UpdateClientError(f"GitHub update request failed with HTTP {response.status_code}")
                    declared = response.headers.get("Content-Length")
                    if declared:
                        try:
                            if int(declared) > max_bytes:
                                raise UpdateClientError("GitHub update response exceeds the allowed size")
                        except ValueError as exc:
                            raise UpdateClientError("GitHub update response has invalid Content-Length") from exc
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes(64 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise UpdateClientError("GitHub update response exceeds the allowed size")
                        chunks.append(chunk)
                    return b"".join(chunks)
        raise UpdateClientError("GitHub update redirect limit exceeded")

    async def _release_list(self) -> list[dict[str, Any]]:
        payload = await self._fetch_bytes(
            UPDATE_API_URL,
            max_bytes=MAX_RELEASE_METADATA_BYTES,
            accept="application/vnd.github+json",
        )
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpdateClientError("GitHub release metadata is invalid") from exc
        if not isinstance(data, list):
            raise UpdateClientError("GitHub release metadata has an unexpected shape")
        return [item for item in data if isinstance(item, dict)]

    async def _trusted_candidate_from_release(
        self,
        release: dict[str, Any],
        *,
        channel: str,
    ) -> UpdateCandidate | None:
        if release.get("draft"):
            return None
        is_prerelease = bool(release.get("prerelease"))
        if channel == "stable" and is_prerelease:
            return None
        if channel == "beta" and not is_prerelease:
            return None

        assets = release.get("assets")
        if not isinstance(assets, list):
            return None
        by_name = {
            str(item.get("name") or ""): item
            for item in assets
            if isinstance(item, dict) and str(item.get("name") or "")
        }
        manifest_asset = by_name.get("update-manifest.json")
        if manifest_asset is None:
            return None

        manifest_url = _validate_remote_url(
            str(manifest_asset.get("browser_download_url") or ""),
            initial_asset=True,
        )
        raw_manifest = await self._fetch_bytes(
            manifest_url,
            max_bytes=MAX_UPDATE_MANIFEST_BYTES,
            initial_asset=True,
            accept="application/json",
        )
        try:
            manifest = SignedUpdateManifest.parse(raw_manifest.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise UpdateClientError("published update manifest is invalid") from exc
        if not verify_manifest_signature(manifest, self.trust_root.public_key):
            raise UpdateClientError("published update manifest signature verification failed")
        try:
            validate_manifest_trust_binding(
                manifest,
                repository=self.trust_root.repository,
                key_id=self.trust_root.key_id,
                public_key_sha256=self.trust_root.public_key_sha256,
            )
        except ValueError as exc:
            raise UpdateClientError(f"published update manifest trust binding failed: {exc}") from exc
        if manifest.artifact.channel != channel:
            raise UpdateClientError("published update manifest channel does not match release channel")

        tag = str(release.get("tag_name") or "").strip()
        if tag != f"v{manifest.artifact.version}":
            raise UpdateClientError("published release tag does not match signed update version")

        installer_asset = by_name.get(manifest.artifact.filename)
        if installer_asset is None:
            raise UpdateClientError("signed update manifest references a missing installer asset")
        installer_url = _validate_remote_url(
            str(installer_asset.get("browser_download_url") or ""),
            initial_asset=True,
        )
        release_url = str(release.get("html_url") or "")
        if release_url:
            _validate_remote_url(release_url)
        return UpdateCandidate(
            release_tag=tag,
            release_url=release_url,
            manifest=manifest,
            installer_url=installer_url,
            manifest_url=manifest_url,
        )

    async def check_for_update(self, current_version: str, *, channel: str = "stable") -> UpdateCandidate | None:
        selected = str(channel or "").strip().lower()
        if selected not in _ALLOWED_CHANNELS:
            raise UpdateClientError("desktop update channel must be stable or beta")
        current_key = _semver_key(current_version)
        candidates: list[UpdateCandidate] = []
        for release in (await self._release_list())[:20]:
            candidate = await self._trusted_candidate_from_release(release, channel=selected)
            if candidate is None:
                continue
            if _semver_key(candidate.manifest.artifact.version) > current_key:
                candidates.append(candidate)
        if not candidates:
            return None
        return max(candidates, key=lambda item: _semver_key(item.manifest.artifact.version))

    async def download_verified_installer(
        self,
        candidate: UpdateCandidate,
        *,
        destination_dir: Path | None = None,
        require_authenticode: bool | None = None,
    ) -> VerifiedUpdateDownload:
        artifact = candidate.manifest.artifact
        if not verify_manifest_signature(candidate.manifest, self.trust_root.public_key):
            raise UpdateClientError("update manifest signature verification failed before download")
        try:
            validate_manifest_trust_binding(
                candidate.manifest,
                repository=self.trust_root.repository,
                key_id=self.trust_root.key_id,
                public_key_sha256=self.trust_root.public_key_sha256,
            )
        except ValueError as exc:
            raise UpdateClientError(f"update manifest trust binding failed before download: {exc}") from exc
        destination = Path(destination_dir) if destination_dir is not None else _desktop_update_root()
        if destination.is_symlink():
            raise UpdateClientError("update destination must not be a symlink")
        destination.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink() or not destination.is_dir():
            raise UpdateClientError("update destination is not a safe directory")

        final_path = destination / artifact.filename
        if final_path.is_symlink():
            raise UpdateClientError("update destination file must not be a symlink")

        current = _validate_remote_url(candidate.installer_url, initial_asset=True)
        headers = {"Accept": "application/octet-stream", "User-Agent": UPDATE_USER_AGENT}
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=destination,
                prefix=".dpn-update-",
                suffix=".part",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                digest = hashlib.sha256()
                written = 0
                async with httpx.AsyncClient(
                    trust_env=False,
                    timeout=self.timeout,
                    follow_redirects=False,
                    transport=self.transport,
                    headers=headers,
                ) as client:
                    for _ in range(MAX_REDIRECTS + 1):
                        async with client.stream("GET", current) as response:
                            if response.status_code in {301, 302, 303, 307, 308}:
                                location = response.headers.get("Location", "")
                                if not location:
                                    raise UpdateClientError("GitHub installer redirect omitted Location")
                                current = _validate_remote_url(urljoin(current, location))
                                continue
                            if response.status_code != 200:
                                raise UpdateClientError(
                                    f"GitHub installer download failed with HTTP {response.status_code}"
                                )
                            declared = response.headers.get("Content-Length")
                            if declared:
                                try:
                                    if int(declared) != artifact.size:
                                        raise UpdateClientError("installer Content-Length does not match signed size")
                                except ValueError as exc:
                                    raise UpdateClientError("installer Content-Length is invalid") from exc
                            async for chunk in response.aiter_bytes(1024 * 1024):
                                written += len(chunk)
                                if written > artifact.size:
                                    raise UpdateClientError("installer download exceeds signed size")
                                digest.update(chunk)
                                handle.write(chunk)
                            break
                    else:
                        raise UpdateClientError("GitHub installer redirect limit exceeded")
                handle.flush()
                os.fsync(handle.fileno())

            if written != artifact.size:
                raise UpdateClientError("installer download size does not match signed manifest")
            if not hmac.compare_digest(digest.hexdigest(), artifact.sha256):
                raise UpdateClientError("installer download SHA-256 does not match signed manifest")
            if final_path.is_symlink():
                raise UpdateClientError("update destination became unsafe during download")
            os.replace(temp_path, final_path)
            temp_path = None
            verify_artifact(final_path, artifact)

            should_verify_authenticode = sys.platform == "win32" if require_authenticode is None else bool(require_authenticode)
            authenticode_verified = False
            if should_verify_authenticode:
                authenticode_verified = verify_windows_authenticode(final_path)
                if not authenticode_verified:
                    final_path.unlink(missing_ok=True)
                    raise UpdateClientError("downloaded installer failed Authenticode verification")

            return VerifiedUpdateDownload(
                path=final_path,
                version=artifact.version,
                channel=artifact.channel,
                sha256=artifact.sha256,
                size=artifact.size,
                authenticode_verified=authenticode_verified,
            )
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)


__all__ = [
    "GitHubReleaseUpdateClient",
    "UpdateCandidate",
    "UpdateClientError",
    "UpdateTrustRoot",
    "VerifiedUpdateDownload",
    "load_packaged_update_trust_root",
    "packaged_update_trust_path",
    "verify_windows_authenticode",
]
