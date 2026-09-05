from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUPPORTED_ARTIFACTS = {".docx", ".pdf", ".xlsx", ".pptx", ".txt", ".md", ".csv"}

_OFFICE_REQUIRED_MEMBERS: dict[str, frozenset[str]] = {
    ".docx": frozenset({"[Content_Types].xml", "word/document.xml"}),
    ".xlsx": frozenset({"[Content_Types].xml", "xl/workbook.xml"}),
    ".pptx": frozenset({"[Content_Types].xml", "ppt/presentation.xml"}),
}


@dataclass(frozen=True)
class ArtifactValidation:
    path: str
    artifact_type: str
    size_bytes: int
    sha256: str
    valid: bool
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "type": self.artifact_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "valid": self.valid,
            "warnings": list(self.warnings),
        }


def _validate_office_container(target: Path, suffix: str) -> list[str]:
    warnings: list[str] = []
    try:
        with zipfile.ZipFile(target, "r") as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                warnings.append(f"corrupt Office container member: {bad_member}")
            members = set(archive.namelist())
            missing = sorted(_OFFICE_REQUIRED_MEMBERS[suffix] - members)
            if missing:
                warnings.append("missing required Office package members: " + ", ".join(missing))
    except (zipfile.BadZipFile, OSError):
        warnings.append("artifact is not a valid Office Open XML container")
    return warnings


def _validate_pdf(payload: bytes) -> list[str]:
    warnings: list[str] = []
    if not payload.startswith(b"%PDF-"):
        warnings.append("missing PDF signature")
    if b"%%EOF" not in payload[-2048:]:
        warnings.append("missing PDF EOF marker")
    return warnings


def validate_artifact(path: Path, workspace: Path) -> ArtifactValidation:
    workspace = workspace.resolve()
    target = path.resolve()
    target.relative_to(workspace)

    warnings: list[str] = []
    suffix = target.suffix.lower()
    if suffix not in SUPPORTED_ARTIFACTS:
        warnings.append(f"unsupported artifact extension: {suffix or '<none>'}")
    if not target.exists() or not target.is_file():
        return ArtifactValidation(
            path=target.relative_to(workspace).as_posix(),
            artifact_type=suffix.lstrip(".") or "unknown",
            size_bytes=0,
            sha256="",
            valid=False,
            warnings=tuple(warnings + ["artifact file is missing"]),
        )

    payload = target.read_bytes()
    if not payload:
        warnings.append("artifact is empty")
    elif suffix in _OFFICE_REQUIRED_MEMBERS:
        warnings.extend(_validate_office_container(target, suffix))
    elif suffix == ".pdf":
        warnings.extend(_validate_pdf(payload))

    structurally_valid = not warnings
    return ArtifactValidation(
        path=target.relative_to(workspace).as_posix(),
        artifact_type=suffix.lstrip(".") or "unknown",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        valid=bool(payload) and suffix in SUPPORTED_ARTIFACTS and structurally_valid,
        warnings=tuple(warnings),
    )
