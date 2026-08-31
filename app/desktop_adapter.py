from __future__ import annotations

import base64
import os
import tempfile
import time
from pathlib import Path
from typing import Any


class DesktopAdapter:
    """Optional local desktop control. Disabled by default and always treated as high-risk."""

    MAX_SCREENSHOT_BYTES = 25_000_000

    def __init__(self, workspace: Path):
        if workspace.is_symlink():
            raise ValueError("Desktop workspace root must not be a symlink")
        self.workspace = workspace.resolve()
        self.output_dir = self.workspace / "generated" / "desktop"
        if self.output_dir.exists() and self.output_dir.is_symlink():
            raise ValueError("Desktop output directory must not be a symlink")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def status() -> dict[str, Any]:
        try:
            import pyautogui  # noqa: F401
            return {"ok": True, "available": True}
        except Exception:
            return {"ok": True, "available": False, "install": "pip install -r requirements-desktop.txt"}

    def _output_path(self, screenshot_name: str, default: str) -> Path:
        safe_name = Path(str(screenshot_name or default)).name
        if safe_name in {"", ".", ".."}:
            safe_name = default
        target = (self.output_dir / safe_name).with_suffix(".png")
        if target.is_symlink():
            raise ValueError("Desktop screenshot target must not be a symlink")
        try:
            target.resolve(strict=False).relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("Desktop screenshot path is outside the workspace") from exc
        return target

    def _save_screenshot(self, pyautogui: Any, target: Path, region: tuple[int, int, int, int] | None = None) -> bytes:
        fd, temporary_name = tempfile.mkstemp(prefix=".dpn-screen-", suffix=".png", dir=self.output_dir)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            image = pyautogui.screenshot(region=region)
            image.save(temporary)
            size = temporary.stat().st_size
            if size > self.MAX_SCREENSHOT_BYTES:
                raise ValueError("Desktop screenshot exceeded 25 MB")
            if target.is_symlink():
                raise ValueError("Desktop screenshot target became a symlink")
            os.replace(temporary, target)
            return target.read_bytes()
        finally:
            temporary.unlink(missing_ok=True)

    def observe(self, screenshot_name: str = "screen-observation.png", region: list[int] | None = None,
                include_image: bool = True) -> dict[str, Any]:
        try:
            import pyautogui
        except Exception:
            return {"ok": False, "error": "pyautogui is not installed. Use requirements-desktop.txt."}
        try:
            target = self._output_path(screenshot_name, "screen-observation.png")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        size = pyautogui.size()
        selected_region = None
        if region:
            if len(region) != 4:
                return {"ok": False, "error": "Region must be [left, top, width, height]"}
            left, top, width, height = (int(item) for item in region)
            if left < 0 or top < 0 or width <= 0 or height <= 0:
                return {"ok": False, "error": "Region values must be non-negative with positive width and height"}
            if left >= size.width or top >= size.height or left + width > size.width or top + height > size.height:
                return {"ok": False, "error": "Region must remain inside the current screen bounds"}
            selected_region = (left, top, width, height)
        try:
            image_bytes = self._save_screenshot(pyautogui, target, selected_region)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        position = pyautogui.position()
        result: dict[str, Any] = {
            "ok": True,
            "screenshot": target.relative_to(self.workspace).as_posix(),
            "screen": {"width": size.width, "height": size.height},
            "cursor": {"x": position.x, "y": position.y},
            "region": list(selected_region) if selected_region else None,
        }
        if include_image:
            result["__images"] = [base64.b64encode(image_bytes).decode("ascii")]
        return result

    def run(self, actions: list[dict[str, Any]], screenshot_name: str = "desktop-result.png") -> dict[str, Any]:
        try:
            import pyautogui
        except Exception:
            return {"ok": False, "error": "pyautogui is not installed. Use requirements-desktop.txt."}
        try:
            target = self._output_path(screenshot_name, "desktop-result.png")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = max(float(getattr(pyautogui, "PAUSE", 0.0)), 0.05)
        screen = pyautogui.size()
        completed: list[dict[str, Any]] = []
        for action in (actions or [])[:30]:
            if not isinstance(action, dict):
                continue
            kind = str(action.get("type") or "")
            if kind in {"click", "move"}:
                x, y = int(action.get("x", 0)), int(action.get("y", 0))
                if x < 0 or y < 0 or x >= screen.width or y >= screen.height:
                    return {"ok": False, "error": f"Desktop {kind} coordinates are outside the current screen"}
                if kind == "click":
                    pyautogui.click(x, y, clicks=max(1, min(int(action.get("clicks", 1)), 3)))
                else:
                    duration = max(0.0, min(float(action.get("duration", 0.2)), 3.0))
                    pyautogui.moveTo(x, y, duration=duration)
            elif kind == "type":
                pyautogui.write(str(action.get("text", ""))[:10_000], interval=max(0.0, min(float(action.get("interval", 0.01)), 1.0)))
            elif kind == "hotkey":
                keys = [str(key)[:50] for key in action.get("keys", [])[:5] if str(key)]
                if not keys:
                    continue
                pyautogui.hotkey(*keys)
            elif kind == "press":
                key = str(action.get("key", "enter"))[:50]
                if not key:
                    continue
                pyautogui.press(key)
            elif kind == "wait":
                time.sleep(max(0.0, min(float(action.get("seconds", 1)), 30.0)))
            else:
                continue
            completed.append(action)
        try:
            image_bytes = self._save_screenshot(pyautogui, target)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "completed": len(completed),
            "screenshot": target.relative_to(self.workspace).as_posix(),
            "__images": [base64.b64encode(image_bytes).decode("ascii")],
        }
