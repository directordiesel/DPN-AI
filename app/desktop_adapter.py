from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any


class DesktopAdapter:
    """Optional local desktop control. Disabled by default and always treated as high-risk."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.output_dir = workspace / "generated" / "desktop"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def status() -> dict[str, Any]:
        try:
            import pyautogui  # noqa: F401
            return {"ok": True, "available": True}
        except Exception:
            return {"ok": True, "available": False, "install": "pip install -r requirements-desktop.txt"}


    def observe(self, screenshot_name: str = "screen-observation.png", region: list[int] | None = None,
                include_image: bool = True) -> dict[str, Any]:
        try:
            import pyautogui
        except Exception:
            return {"ok": False, "error": "pyautogui is not installed. Use requirements-desktop.txt."}
        target = self.output_dir / Path(screenshot_name).name
        selected_region = None
        if region:
            if len(region) != 4:
                return {"ok": False, "error": "Region must be [left, top, width, height]"}
            selected_region = tuple(max(0, int(item)) for item in region)
            if selected_region[2] <= 0 or selected_region[3] <= 0:
                return {"ok": False, "error": "Region width and height must be positive"}
        image = pyautogui.screenshot(region=selected_region)
        image.save(target)
        position = pyautogui.position()
        size = pyautogui.size()
        result: dict[str, Any] = {
            "ok": True,
            "screenshot": target.relative_to(self.workspace).as_posix(),
            "screen": {"width": size.width, "height": size.height},
            "cursor": {"x": position.x, "y": position.y},
            "region": list(selected_region) if selected_region else None,
        }
        if include_image:
            result["__images"] = [base64.b64encode(target.read_bytes()).decode("ascii")]
        return result

    def run(self, actions: list[dict[str, Any]], screenshot_name: str = "desktop-result.png") -> dict[str, Any]:
        try:
            import pyautogui
        except Exception:
            return {"ok": False, "error": "pyautogui is not installed. Use requirements-desktop.txt."}
        pyautogui.FAILSAFE = True
        completed = []
        for action in actions[:30]:
            kind = action.get("type")
            if kind == "click":
                pyautogui.click(int(action.get("x", 0)), int(action.get("y", 0)), clicks=max(1, min(int(action.get("clicks", 1)), 3)))
            elif kind == "move":
                pyautogui.moveTo(int(action.get("x", 0)), int(action.get("y", 0)), duration=min(float(action.get("duration", 0.2)), 3.0))
            elif kind == "type":
                pyautogui.write(str(action.get("text", ""))[:10_000], interval=max(0.0, min(float(action.get("interval", 0.01)), 1.0)))
            elif kind == "hotkey":
                keys = [str(key) for key in action.get("keys", [])[:5]]
                pyautogui.hotkey(*keys)
            elif kind == "press":
                pyautogui.press(str(action.get("key", "enter")))
            elif kind == "wait":
                time.sleep(max(0.0, min(float(action.get("seconds", 1)), 30.0)))
            else:
                continue
            completed.append(action)
        target = self.output_dir / Path(screenshot_name).name
        pyautogui.screenshot(str(target))
        return {"ok": True, "completed": len(completed), "screenshot": target.relative_to(self.workspace).as_posix(), "__images": [base64.b64encode(target.read_bytes()).decode("ascii")]}