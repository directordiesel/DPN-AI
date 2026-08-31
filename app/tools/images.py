from __future__ import annotations

import copy
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

import httpx


class ComfyUIImageGenerator:
    """Run a user-supplied local ComfyUI workflow exported in API format."""

    def __init__(self, base_url: str, workflow_path: Path, workspace: Path):
        self.base_url = base_url.rstrip("/")
        self.workflow_path = workflow_path.resolve()
        self.workspace = workspace.resolve()
        self.output_dir = self.workspace / "generated" / "images"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_prefix(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
        return cleaned[:80] or "DPN_AI"

    def _load_workflow(self) -> dict[str, Any]:
        if not self.workflow_path.exists():
            raise FileNotFoundError(
                "No ComfyUI API workflow is configured. In ComfyUI, use File → Export Workflow (API), "
                f"then save it as {self.workflow_path}."
            )
        data = json.loads(self.workflow_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data:
            raise ValueError("The ComfyUI workflow must be a non-empty JSON object in API format")
        return data

    @staticmethod
    def _apply_prompt(workflow: dict[str, Any], prompt: str, negative_prompt: str, seed: int, prefix: str) -> dict[str, Any]:
        updated = copy.deepcopy(workflow)
        clip_nodes: list[tuple[str, dict[str, Any]]] = []
        for node_id, node in updated.items():
            if not isinstance(node, dict):
                continue
            class_type = str(node.get("class_type", ""))
            inputs = node.setdefault("inputs", {})
            title = str((node.get("_meta") or {}).get("title", "")).lower()
            if class_type == "CLIPTextEncode" and isinstance(inputs, dict):
                clip_nodes.append((title, node))
            if class_type in {"KSampler", "KSamplerAdvanced", "RandomNoise"} and isinstance(inputs, dict):
                if "seed" in inputs:
                    inputs["seed"] = seed
                if "noise_seed" in inputs:
                    inputs["noise_seed"] = seed
            if class_type == "SaveImage" and isinstance(inputs, dict):
                inputs["filename_prefix"] = prefix

        positive_set = False
        negative_set = False
        for title, node in clip_nodes:
            inputs = node["inputs"]
            if "negative" in title and not negative_set:
                inputs["text"] = negative_prompt
                negative_set = True
            elif any(word in title for word in ("positive", "prompt")) and not positive_set:
                inputs["text"] = prompt
                positive_set = True
        for _title, node in clip_nodes:
            inputs = node["inputs"]
            current = str(inputs.get("text", ""))
            if not positive_set:
                inputs["text"] = prompt
                positive_set = True
            elif not negative_set and current != prompt:
                inputs["text"] = negative_prompt
                negative_set = True
                break
        if not positive_set:
            raise ValueError("Workflow has no CLIPTextEncode node that DPN AI can populate")
        return updated

    async def generate(
        self,
        prompt: str,
        negative_prompt: str = "low quality, blurry, distorted, watermark, text artifacts",
        filename_prefix: str = "DPN_AI",
        seed: int | None = None,
        timeout_seconds: int = 300,
    ) -> dict[str, Any]:
        try:
            workflow = self._load_workflow()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        actual_seed = int(seed if seed is not None else time.time_ns() % 2_147_483_647)
        prefix = self._safe_prefix(filename_prefix)
        try:
            workflow = self._apply_prompt(workflow, prompt, negative_prompt, actual_seed, prefix)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Cannot prepare ComfyUI workflow: {exc}"}

        timeout_seconds = max(30, min(int(timeout_seconds), 1800))
        client_id = str(uuid.uuid4())
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                queued = await client.post(
                    f"{self.base_url}/prompt",
                    json={"prompt": workflow, "client_id": client_id},
                )
                queued.raise_for_status()
                queue_data = queued.json()
                prompt_id = queue_data.get("prompt_id")
                if not prompt_id:
                    return {"ok": False, "error": f"ComfyUI rejected the workflow: {queue_data}"}

                deadline = time.monotonic() + timeout_seconds
                history_entry: dict[str, Any] | None = None
                while time.monotonic() < deadline:
                    history_response = await client.get(f"{self.base_url}/history/{prompt_id}")
                    history_response.raise_for_status()
                    history_data = history_response.json()
                    entry = history_data.get(prompt_id)
                    if entry:
                        history_entry = entry
                        status = entry.get("status") or {}
                        if status.get("status_str") == "error":
                            return {"ok": False, "error": f"ComfyUI execution failed: {status}"}
                        if entry.get("outputs"):
                            break
                    await __import__("asyncio").sleep(1)
                if not history_entry or not history_entry.get("outputs"):
                    return {"ok": False, "error": f"ComfyUI did not finish within {timeout_seconds} seconds"}

                saved: list[str] = []
                for output in history_entry["outputs"].values():
                    for image in output.get("images", []) if isinstance(output, dict) else []:
                        params = {
                            "filename": image.get("filename", ""),
                            "subfolder": image.get("subfolder", ""),
                            "type": image.get("type", "output"),
                        }
                        image_response = await client.get(f"{self.base_url}/view", params=params)
                        image_response.raise_for_status()
                        original_name = Path(str(params["filename"])).name
                        suffix = Path(original_name).suffix or ".png"
                        target = self.output_dir / f"{prefix}_{len(saved) + 1}_{actual_seed}{suffix}"
                        target.write_bytes(image_response.content)
                        saved.append(target.relative_to(self.workspace).as_posix())
                if not saved:
                    return {"ok": False, "error": "ComfyUI completed but returned no image outputs"}
                return {"ok": True, "paths": saved, "path": saved[0], "seed": actual_seed, "prompt_id": prompt_id}
        except httpx.ConnectError:
            return {"ok": False, "error": f"Cannot reach local ComfyUI at {self.base_url}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"ComfyUI generation failed: {type(exc).__name__}: {exc}"}