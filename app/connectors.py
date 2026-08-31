from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.db import Database
from app.vault import SecretVault


class ConnectorHub:
    """Allow-listed generic HTTP connector framework with encrypted secret templates."""

    def __init__(self, db: Database, vault: SecretVault, allow_private_network: bool = False):
        self.db = db
        self.vault = vault
        self.allow_private_network = allow_private_network

    def create(self, name: str, base_url: str, headers: dict[str, str] | None = None,
               allowed_methods: list[str] | None = None, enabled: bool = True) -> dict[str, Any]:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return {"ok": False, "error": "Connector base_url must be HTTP or HTTPS"}
        config = {
            "base_url": base_url.rstrip("/") + "/",
            "headers": headers or {},
            "allowed_methods": sorted({m.upper() for m in (allowed_methods or ["GET"])}),
        }
        connector = self.db.create_connector(name.strip(), "http", config, enabled)
        return {"ok": True, "connector": connector}

    def list(self) -> dict[str, Any]:
        connectors = self.db.list_connectors()
        for item in connectors:
            headers = item.get("config", {}).get("headers", {})
            item["config"]["headers"] = {key: "[configured]" for key in headers}
        return {"ok": True, "connectors": connectors}

    @staticmethod
    def _is_private_host(host: str) -> bool:
        try:
            addresses = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return False
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return True
        return False

    async def request(self, connector_id: str, method: str = "GET", path: str = "",
                      params: dict[str, Any] | None = None, json_body: Any = None,
                      timeout_seconds: int = 30) -> dict[str, Any]:
        connector = self.db.get_connector(connector_id)
        if not connector or not connector.get("enabled"):
            return {"ok": False, "error": "Connector not found or disabled"}
        config = connector.get("config", {})
        method = method.upper()
        if method not in config.get("allowed_methods", ["GET"]):
            return {"ok": False, "error": f"Method {method} is not allow-listed for this connector"}
        base_url = config.get("base_url", "")
        url = urljoin(base_url, path.lstrip("/"))
        parsed_base, parsed_url = urlparse(base_url), urlparse(url)
        if parsed_url.scheme != parsed_base.scheme or parsed_url.netloc != parsed_base.netloc:
            return {"ok": False, "error": "Connector path escaped the configured host"}
        if not self.allow_private_network and parsed_url.hostname and self._is_private_host(parsed_url.hostname):
            return {"ok": False, "error": "Private-network connector access is disabled"}
        try:
            headers = self.vault.resolve(config.get("headers", {}))
            body = self.vault.resolve(json_body)
            async with httpx.AsyncClient(timeout=max(5, min(timeout_seconds, 120)), follow_redirects=False) as client:
                response = await client.request(method, url, params=params, json=body, headers=headers)
            text = response.text[:100_000]
            content_type = response.headers.get("content-type", "")
            parsed: Any = text
            if "json" in content_type:
                try:
                    parsed = response.json()
                except Exception:
                    pass
            return {
                "ok": response.status_code < 400,
                "status_code": response.status_code,
                "url": str(response.url),
                "content_type": content_type,
                "response": parsed,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Connector request failed: {type(exc).__name__}: {exc}"}