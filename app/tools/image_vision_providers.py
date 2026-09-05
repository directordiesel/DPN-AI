from __future__ import annotations

import base64
import copy
import hashlib
import json
import mimetypes
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

import httpx


_MAX_IMAGE_BYTES = 25 * 1024 * 1024


def _safe_prefix(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "DPN_AI")).strip("._")
    return cleaned[:80] or "DPN_AI"


def _workspace_file(workspace: Path, raw_path: str) -> Path:
    root = workspace.resolve()
    candidate = (root / str(raw_path)).resolve() if not Path(str(raw_path)).is_absolute() else Path(str(raw_path)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("Image path must remain inside the DPN AI workspace") from exc
    if not candidate.is_file():
        raise FileNotFoundError(f"Image file does not exist: {raw_path}")
    size = candidate.stat().st_size
    if size <= 0:
        raise ValueError("Image file is empty")
    if size > _MAX_IMAGE_BYTES:
        raise ValueError(f"Image exceeds the {_MAX_IMAGE_BYTES // (1024 * 1024)} MB provider limit")
    return candidate


def _image_mime(path: Path, payload: bytes) -> str:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload[:6] in {b"GIF87a", b"GIF89a"}:
        return "image/gif"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return "image/webp"
    guessed = mimetypes.guess_type(path.name)[0] or ""
    if guessed.startswith("image/"):
        return guessed
    raise ValueError("Unsupported or unrecognized image format")


class ConfigurableVisionProvider:
    """Analyze workspace images through an explicitly configured multimodal model."""

    def __init__(self, gateway: Any, workspace: Path, configured_model: str = ""):
        self.gateway = gateway
        self.workspace = workspace.resolve()
        self.configured_model = str(configured_model or "").strip()

    async def analyze(
        self,
        reference_image: str,
        prompt: str = "Analyze this image accurately and describe the important visual evidence.",
        model: str = "",
    ) -> dict[str, Any]:
        selected = str(model or self.configured_model).strip()
        if not selected:
            return {
                "ok": False,
                "configured": False,
                "error": "No vision model is configured. Set DPN_VISION_MODEL or pass an explicit vision-capable model.",
            }
        try:
            path = _workspace_file(self.workspace, reference_image)
            payload = path.read_bytes()
            mime = _image_mime(path, payload)
            encoded = base64.b64encode(payload).decode("ascii")
            result = await self.gateway.chat(
                model=selected,
                messages=[{
                    "role": "user",
                    "content": str(prompt or "Analyze this image accurately."),
                    "images": [f"data:{mime};base64,{encoded}"],
                }],
                tools=None,
                think=False,
            )
            content = str((result.get("message") or {}).get("content") or "").strip()
            if not content:
                return {"ok": False, "configured": True, "model": selected, "error": "Vision provider returned no analysis text"}
            return {
                "ok": True,
                "configured": True,
                "model": result.get("model") or selected,
                "provider": result.get("provider") or "configured_model_gateway",
                "analysis": content,
                "reference_image": path.relative_to(self.workspace).as_posix(),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "mime_type": mime,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "configured": True, "model": selected, "error": f"Vision analysis failed: {type(exc).__name__}: {exc}"}


class ComfyUIImageEditor:
    """Run a user-supplied ComfyUI img2img/edit workflow against a workspace image."""

    def __init__(self, base_url: str, workflow_path: Path | str, workspace: Path):
        self.base_url = str(base_url).rstrip("/")
        self.workflow_path = Path(workflow_path).resolve() if str(workflow_path or "").strip() else None
        self.workspace = workspace.resolve()
        self.output_dir = self.workspace / "generated" / "images"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _load_workflow(self) -> dict[str, Any]:
        if self.workflow_path is None:
            raise FileNotFoundError("No ComfyUI image-edit workflow is configured. Set DPN_COMFYUI_EDIT_WORKFLOW.")
        if not self.workflow_path.is_file():
            raise FileNotFoundError(f"Configured ComfyUI edit workflow does not exist: {self.workflow_path}")
        data = json.loads(self.workflow_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data:
            raise ValueError("ComfyUI edit workflow must be a non-empty API-format JSON object")
        return data

    @staticmethod
    def _prepare_workflow(workflow: dict[str, Any], uploaded_name: str, prompt: str, negative_prompt: str, seed: int, prefix: str) -> dict[str, Any]:
        updated = copy.deepcopy(workflow)
        load_nodes: list[dict[str, Any]] = []
        clip_nodes: list[tuple[str, dict[str, Any]]] = []
        for node in updated.values():
            if not isinstance(node, dict):
                continue
            class_type = str(node.get("class_type") or "")
            inputs = node.setdefault("inputs", {})
            if not isinstance(inputs, dict):
                continue
            title = str((node.get("_meta") or {}).get("title", "")).lower()
            if class_type in {"LoadImage", "LoadImageMask"}:
                load_nodes.append(node)
            if class_type == "CLIPTextEncode":
                clip_nodes.append((title, node))
            if class_type in {"KSampler", "KSamplerAdvanced", "RandomNoise"}:
                if "seed" in inputs:
                    inputs["seed"] = seed
                if "noise_seed" in inputs:
                    inputs["noise_seed"] = seed
            if class_type == "SaveImage":
                inputs["filename_prefix"] = prefix
        if not load_nodes:
            raise ValueError("Edit workflow has no LoadImage/LoadImageMask node for the reference image")
        load_nodes[0]["inputs"]["image"] = uploaded_name

        positive_set = False
        negative_set = False
        for title, node in clip_nodes:
            if "negative" in title and not negative_set:
                node["inputs"]["text"] = negative_prompt
                negative_set = True
            elif any(token in title for token in ("positive", "prompt")) and not positive_set:
                node["inputs"]["text"] = prompt
                positive_set = True
        for _title, node in clip_nodes:
            current = str(node["inputs"].get("text", ""))
            if not positive_set:
                node["inputs"]["text"] = prompt
                positive_set = True
            elif not negative_set and current != prompt:
                node["inputs"]["text"] = negative_prompt
                negative_set = True
                break
        if not positive_set:
            raise ValueError("Edit workflow has no CLIPTextEncode node that DPN AI can populate")
        return updated

    async def edit(
        self,
        reference_image: str,
        prompt: str,
        negative_prompt: str = "low quality, blurry, distorted, watermark, text artifacts",
        filename_prefix: str = "DPN_AI_EDIT",
        seed: int | None = None,
        timeout_seconds: int = 300,
    ) -> dict[str, Any]:
        if self.workflow_path is None:
            return {"ok": False, "configured": False, "error": "No ComfyUI image-edit workflow is configured. Set DPN_COMFYUI_EDIT_WORKFLOW."}
        try:
            path = _workspace_file(self.workspace, reference_image)
            payload = path.read_bytes()
            mime = _image_mime(path, payload)
            workflow = self._load_workflow()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "configured": bool(self.workflow_path), "error": str(exc)}

        actual_seed = int(seed if seed is not None else time.time_ns() % 2_147_483_647)
        prefix = _safe_prefix(filename_prefix)
        timeout_seconds = max(30, min(int(timeout_seconds), 1800))
        upload_name = f"dpn_ai_edit_{uuid.uuid4().hex}_{path.name}"
        client_id = str(uuid.uuid4())
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                upload = await client.post(
                    f"{self.base_url}/upload/image",
                    files={"image": (upload_name, payload, mime)},
                    data={"overwrite": "true"},
                )
                upload.raise_for_status()
                upload_data = upload.json() if upload.content else {}
                uploaded_name = str(upload_data.get("name") or upload_name)
                prepared = self._prepare_workflow(workflow, uploaded_name, str(prompt), str(negative_prompt), actual_seed, prefix)
                queued = await client.post(f"{self.base_url}/prompt", json={"prompt": prepared, "client_id": client_id})
                queued.raise_for_status()
                prompt_id = queued.json().get("prompt_id")
                if not prompt_id:
                    return {"ok": False, "configured": True, "error": "ComfyUI rejected the image-edit workflow"}

                deadline = time.monotonic() + timeout_seconds
                entry: dict[str, Any] | None = None
                while time.monotonic() < deadline:
                    history = await client.get(f"{self.base_url}/history/{prompt_id}")
                    history.raise_for_status()
                    entry = history.json().get(prompt_id)
                    if entry:
                        status = entry.get("status") or {}
                        if status.get("status_str") == "error":
                            return {"ok": False, "configured": True, "error": f"ComfyUI image edit failed: {status}"}
                        if entry.get("outputs"):
                            break
                    await __import__("asyncio").sleep(1)
                if not entry or not entry.get("outputs"):
                    return {"ok": False, "configured": True, "error": f"ComfyUI image edit did not finish within {timeout_seconds} seconds"}

                saved: list[str] = []
                for output in entry["outputs"].values():
                    for image in output.get("images", []) if isinstance(output, dict) else []:
                        params = {
                            "filename": image.get("filename", ""),
                            "subfolder": image.get("subfolder", ""),
                            "type": image.get("type", "output"),
                        }
                        response = await client.get(f"{self.base_url}/view", params=params)
                        response.raise_for_status()
                        suffix = Path(str(params["filename"])).suffix or ".png"
                        target = self.output_dir / f"{prefix}_{len(saved) + 1}_{actual_seed}{suffix}"
                        target.write_bytes(response.content)
                        saved.append(target.relative_to(self.workspace).as_posix())
                if not saved:
                    return {"ok": False, "configured": True, "error": "ComfyUI edit completed but returned no image outputs"}
                return {
                    "ok": True,
                    "configured": True,
                    "paths": saved,
                    "path": saved[0],
                    "seed": actual_seed,
                    "prompt_id": prompt_id,
                    "reference_image": path.relative_to(self.workspace).as_posix(),
                    "reference_sha256": hashlib.sha256(payload).hexdigest(),
                    "provider": "comfyui",
                }
        except httpx.ConnectError:
            return {"ok": False, "configured": True, "error": f"Cannot reach configured ComfyUI at {self.base_url}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "configured": True, "error": f"ComfyUI image editing failed: {type(exc).__name__}: {exc}"}
