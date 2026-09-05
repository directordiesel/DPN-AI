from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUPPORTED_ARTIFACTS = {".docx", ".pdf", ".xlsx", ".pptx", ".txt", ".md", ".csv"}


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

    return ArtifactValidation(
        path=target.relative_to(workspace).as_posix(),
        artifact_type=suffix.lstrip(".") or "unknown",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        valid=bool(payload) and suffix in SUPPORTED_ARTIFACTS,
        warnings=tuple(warnings),
    )
