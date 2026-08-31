from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.connectors import ConnectorHub


class BrowserAdapter:
    """Optional Playwright adapter with bounded network and screenshot behavior."""

    def __init__(self, workspace: Path, allow_private_network: bool = False):
        if workspace.is_symlink():
            raise ValueError("Browser workspace root must not be a symlink")
        self.workspace = workspace.resolve()
        self.allow_private_network = allow_private_network
        self.output_dir = self.workspace / "generated" / "browser"
        if self.output_dir.exists() and self.output_dir.is_symlink():
            raise ValueError("Browser output directory must not be a symlink")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def status() -> dict[str, Any]:
        try:
            import playwright  # noqa: F401
            return {"ok": True, "available": True}
        except Exception:
            return {"ok": True, "available": False, "install": "pip install -r requirements-browser.txt && playwright install chromium"}

    def _validate_url(self, url: str) -> tuple[bool, str]:
        parsed = urlparse(str(url).strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False, "Browser URL must use HTTP or HTTPS"
        if parsed.username or parsed.password:
            return False, "Browser URL must not contain embedded credentials"
        if not self.allow_private_network and ConnectorHub._is_private_host(parsed.hostname):
            return False, "Private, reserved, or unresolved browser hosts are disabled"
        return True, ""

    def _output_path(self, screenshot_name: str) -> Path:
        safe_name = Path(str(screenshot_name or "browser-result.png")).name
        if safe_name in {"", ".", ".."}:
            safe_name = "browser-result.png"
        target = (self.output_dir / safe_name).with_suffix(".png")
        if target.is_symlink():
            raise ValueError("Browser screenshot target must not be a symlink")
        try:
            target.resolve(strict=False).relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("Browser screenshot path is outside the workspace") from exc
        return target

    async def run(self, url: str, actions: list[dict[str, Any]] | None = None,
                  screenshot_name: str = "browser-result.png", headless: bool = True) -> dict[str, Any]:
        valid, reason = self._validate_url(url)
        if not valid:
            return {"ok": False, "error": reason}
        try:
            screenshot_path = self._output_path(screenshot_name)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        try:
            from playwright.async_api import async_playwright
        except Exception:
            return {"ok": False, "error": "Playwright is not installed. Use requirements-browser.txt."}

        extracted = ""
        events: list[dict[str, Any]] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context(
                viewport={"width": 1440, "height": 1000},
                accept_downloads=False,
                ignore_https_errors=False,
            )
            page = await context.new_page()

            async def guard_route(route: Any) -> None:
                request_url = str(route.request.url)
                parsed = urlparse(request_url)
                if parsed.scheme in {"http", "https"}:
                    allowed, _ = self._validate_url(request_url)
                    if not allowed:
                        await route.abort("blockedbyclient")
                        return
                elif parsed.scheme not in {"about", "data", "blob"}:
                    await route.abort("blockedbyclient")
                    return
                await route.continue_()

            # Guard every navigation and subresource, not only user-supplied goto
            # values. This blocks redirect/subresource pivots to private networks.
            await context.route("**/*", guard_route)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                final_valid, final_reason = self._validate_url(page.url)
                if not final_valid:
                    raise ValueError(final_reason)

                for action in (actions or [])[:30]:
                    if not isinstance(action, dict):
                        events.append({"action": "[invalid]", "status": "ignored"})
                        continue
                    kind = str(action.get("type") or "")
                    selector = str(action.get("selector") or "")[:2000]
                    if kind == "click" and selector:
                        await page.locator(selector).click(timeout=20_000)
                    elif kind == "fill" and selector:
                        await page.locator(selector).fill(str(action.get("value", ""))[:100_000], timeout=20_000)
                    elif kind == "press" and selector:
                        await page.locator(selector).press(str(action.get("key", "Enter"))[:100], timeout=20_000)
                    elif kind == "wait":
                        await page.wait_for_timeout(max(0, min(int(action.get("milliseconds", 1000)), 30_000)))
                    elif kind == "navigate":
                        target = str(action.get("url", ""))
                        target_valid, target_reason = self._validate_url(target)
                        if not target_valid:
                            raise ValueError(target_reason)
                        await page.goto(target, wait_until="domcontentloaded", timeout=60_000)
                    else:
                        events.append({"action": action, "status": "ignored"})
                        continue
                    final_valid, final_reason = self._validate_url(page.url)
                    if not final_valid:
                        raise ValueError(final_reason)
                    events.append({"action": action, "status": "completed"})

                extracted = (await page.locator("body").inner_text())[:100_000]
                # Viewport-only screenshots prevent a hostile page from creating an
                # effectively unbounded full-page image in memory/on disk.
                await page.screenshot(path=str(screenshot_path), full_page=False)
                image_bytes = screenshot_path.read_bytes()
                if len(image_bytes) > 25_000_000:
                    screenshot_path.unlink(missing_ok=True)
                    return {"ok": False, "error": "Browser screenshot exceeded 25 MB"}
                return {
                    "ok": True, "final_url": page.url, "title": (await page.title())[:2000], "text": extracted,
                    "screenshot": screenshot_path.relative_to(self.workspace).as_posix(), "events": events,
                    "__images": [base64.b64encode(image_bytes).decode("ascii")],
                }
            finally:
                await context.close()
                await browser.close()
