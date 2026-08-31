from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.connectors import ConnectorHub


class BrowserAdapter:
    """Optional Playwright adapter. Install requirements-browser.txt to enable it."""

    def __init__(self, workspace: Path, allow_private_network: bool = False):
        self.workspace = workspace
        self.allow_private_network = allow_private_network
        self.output_dir = workspace / "generated" / "browser"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def status() -> dict[str, Any]:
        try:
            import playwright  # noqa: F401
            return {"ok": True, "available": True}
        except Exception:
            return {"ok": True, "available": False, "install": "pip install -r requirements-browser.txt && playwright install chromium"}

    async def run(self, url: str, actions: list[dict[str, Any]] | None = None,
                  screenshot_name: str = "browser-result.png", headless: bool = True) -> dict[str, Any]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return {"ok": False, "error": "Browser URL must use HTTP or HTTPS"}
        if parsed.hostname and not self.allow_private_network and ConnectorHub._is_private_host(parsed.hostname):
            return {"ok": False, "error": "Private-network browser access is disabled"}
        try:
            from playwright.async_api import async_playwright
        except Exception:
            return {"ok": False, "error": "Playwright is not installed. Use requirements-browser.txt."}
        safe_name = Path(screenshot_name).name
        screenshot_path = self.output_dir / safe_name
        extracted = ""
        events: list[dict[str, Any]] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                for action in (actions or [])[:30]:
                    kind = action.get("type")
                    selector = action.get("selector")
                    if kind == "click" and selector:
                        await page.locator(selector).click(timeout=20_000)
                    elif kind == "fill" and selector:
                        await page.locator(selector).fill(str(action.get("value", "")), timeout=20_000)
                    elif kind == "press" and selector:
                        await page.locator(selector).press(str(action.get("key", "Enter")), timeout=20_000)
                    elif kind == "wait":
                        await page.wait_for_timeout(max(0, min(int(action.get("milliseconds", 1000)), 30_000)))
                    elif kind == "navigate":
                        target = str(action.get("url", ""))
                        parsed_target = urlparse(target)
                        if parsed_target.scheme not in {"http", "https"}:
                            raise ValueError("Navigation URL must use HTTP or HTTPS")
                        if parsed_target.hostname and not self.allow_private_network and ConnectorHub._is_private_host(parsed_target.hostname):
                            raise ValueError("Private-network browser access is disabled")
                        await page.goto(target, wait_until="domcontentloaded", timeout=60_000)
                    else:
                        events.append({"action": action, "status": "ignored"})
                        continue
                    events.append({"action": action, "status": "completed"})
                extracted = (await page.locator("body").inner_text())[:100_000]
                await page.screenshot(path=str(screenshot_path), full_page=True)
                return {
                    "ok": True, "final_url": page.url, "title": await page.title(), "text": extracted,
                    "screenshot": screenshot_path.relative_to(self.workspace).as_posix(), "events": events,
                    "__images": [base64.b64encode(screenshot_path.read_bytes()).decode("ascii")],
                }
            finally:
                await browser.close()