from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class ImageOperation(str, Enum):
    GENERATE = "generate"
    EDIT = "edit"
    ANALYZE = "analyze"


@dataclass(frozen=True)
class ImageRequest:
    operation: ImageOperation
    prompt: str
    source_path: str | None = None
    mask_path: str | None = None
    width: int | None = None
    height: int | None = None


class ImageIntelligence:
    """Deterministic request validation and routing metadata for image work."""

    SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
    MAX_DIMENSION = 4096

    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()

    def _resolve_source(self, raw_path: str) -> Path:
        normalized = str(raw_path).strip().lstrip("/\\")
        if not normalized:
            raise ValueError("Image path is required")
        target = (self.workspace / normalized).resolve()
        try:
            target.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("Image path escapes the workspace") from exc
        if not target.exists() or not target.is_file():
            raise ValueError("Image source does not exist")
        if target.suffix.lower() not in self.SUPPORTED_SUFFIXES:
            raise ValueError(f"Unsupported image format: {target.suffix.lower() or 'unknown'}")
        return target

    @staticmethod
    def _bounded_dimension(value: int | None) -> int | None:
        if value is None:
            return None
        number = int(value)
        if number < 64 or number > ImageIntelligence.MAX_DIMENSION:
            raise ValueError("Image dimensions must be between 64 and 4096 pixels")
        return number

    def validate(self, request: ImageRequest) -> dict[str, Any]:
        prompt = request.prompt.strip()
        if not prompt:
            raise ValueError("Image prompt/instruction is required")

        width = self._bounded_dimension(request.width)
        height = self._bounded_dimension(request.height)
        source: Path | None = None
        mask: Path | None = None

        if request.operation in {ImageOperation.EDIT, ImageOperation.ANALYZE}:
            if not request.source_path:
                raise ValueError(f"{request.operation.value} requires source_path")
            source = self._resolve_source(request.source_path)
        elif request.source_path:
            source = self._resolve_source(request.source_path)

        if request.mask_path:
            if request.operation != ImageOperation.EDIT:
                raise ValueError("mask_path is only valid for edit operations")
            mask = self._resolve_source(request.mask_path)

        fingerprint_input = "|".join(
            [
                request.operation.value,
                prompt,
                str(source.relative_to(self.workspace).as_posix() if source else ""),
                str(mask.relative_to(self.workspace).as_posix() if mask else ""),
                str(width or ""),
                str(height or ""),
            ]
        )
        request_id = hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest()[:20]

        return {
            "ok": True,
            "request_id": request_id,
            "operation": request.operation.value,
            "prompt": prompt,
            "source_path": source.relative_to(self.workspace).as_posix() if source else None,
            "mask_path": mask.relative_to(self.workspace).as_posix() if mask else None,
            "width": width,
            "height": height,
            "requires_source": request.operation in {ImageOperation.EDIT, ImageOperation.ANALYZE},
            "provider_capability": {
                ImageOperation.GENERATE: "text_to_image",
                ImageOperation.EDIT: "image_edit",
                ImageOperation.ANALYZE: "vision",
            }[request.operation],
        }

    def build_request(
        self,
        operation: str,
        prompt: str,
        source_path: str | None = None,
        mask_path: str | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any]:
        try:
            op = ImageOperation(str(operation).strip().lower())
        except ValueError as exc:
            raise ValueError("operation must be generate, edit, or analyze") from exc
        return self.validate(
            ImageRequest(
                operation=op,
                prompt=prompt,
                source_path=source_path,
                mask_path=mask_path,
                width=width,
                height=height,
            )
        )
