from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.db import Database
from app.vault import SecretVault


SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"}


class ConnectorHub:
    """Allow-listed generic HTTP connector framework with encrypted secret templates."""

    def __init__(self, db: Database, vault: SecretVault, allow_private_network: bool = False):
        self.db = db
        self.vault = vault
        self.allow_private_network = allow_private_network

    @staticmethod
    def _normalized_methods(methods: list[str] | None) -> tuple[bool, list[str] | str]:
        requested = {str(method).strip().upper() for method in (methods or ["GET"]) if str(method).strip()}
        if not requested:
            requested = {"GET"}
        unsupported = requested - SAFE_HTTP_METHODS
        if unsupported:
            return False, f"Unsupported connector method(s): {', '.join(sorted(unsupported))}"
        return True, sorted(requested)

    @staticmethod
    def _is_private_host(host: str) -> bool:
        """Fail closed: unresolved or non-public hosts are unsafe for public-only connectors."""
        try:
            addresses = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return True
        if not addresses:
            return True
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address[4][0])
            except ValueError:
                return True
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                return True
        return False

    def _validate_base_url(self, base_url: str) -> tuple[bool, str]:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False, "Connector base_url must be HTTP or HTTPS"
        if parsed.username or parsed.password:
            return False, "Connector base_url must not contain embedded credentials"
        if parsed.fragment:
            return False, "Connector base_url must not contain a URL fragment"
        if parsed.query:
            return False, "Connector base_url must not contain a query string"
        if not self.allow_private_network and self._is_private_host(parsed.hostname):
            return False, "Private, reserved, or unresolved connector hosts are disabled"
        return True, ""

    def create(self, name: str, base_url: str, headers: dict[str, str] | None = None,
               allowed_methods: list[str] | None = None, enabled: bool = True) -> dict[str, Any]:
        valid, reason = self._validate_base_url(base_url)
        if not valid:
            return {"ok": False, "error": reason}
        methods_ok, methods = self._normalized_methods(allowed_methods)
        if not methods_ok:
            return {"ok": False, "error": methods}
        config = {
            "base_url": base_url.rstrip("/") + "/",
            "headers": headers or {},
            "allowed_methods": methods,
        }
        connector = self.db.create_connector(name.strip(), "http", config, enabled)
        return {"ok": True, "connector": connector}

    def list(self) -> dict[str, Any]:
        connectors = self.db.list_connectors()
        for item in connectors:
            headers = item.get("config", {}).get("headers", {})
            item["config"]["headers"] = {key: "[configured]" for key in headers}
        return {"ok": True, "connectors": connectors}

    async def request(self, connector_id: str, method: str = "GET", path: str = "",
                      params: dict[str, Any] | None = None, json_body: Any = None,
                      timeout_seconds: int = 30) -> dict[str, Any]:
        connector = self.db.get_connector(connector_id)
        if not connector or not connector.get("enabled"):
            return {"ok": False, "error": "Connector not found or disabled"}
        config = connector.get("config", {})
        method = method.upper()
        if method not in SAFE_HTTP_METHODS:
            return {"ok": False, "error": f"HTTP method {method} is not supported"}
        if method not in config.get("allowed_methods", ["GET"]):
            return {"ok": False, "error": f"Method {method} is not allow-listed for this connector"}
        base_url = config.get("base_url", "")
        valid, reason = self._validate_base_url(base_url)
        if not valid:
            return {"ok": False, "error": reason}
        url = urljoin(base_url, path.lstrip("/"))
        parsed_base, parsed_url = urlparse(base_url), urlparse(url)
        if parsed_url.scheme != parsed_base.scheme or parsed_url.netloc != parsed_base.netloc:
            return {"ok": False, "error": "Connector path escaped the configured host"}
        if parsed_url.username or parsed_url.password:
            return {"ok": False, "error": "Connector request URL must not contain embedded credentials"}
        if not self.allow_private_network and parsed_url.hostname and self._is_private_host(parsed_url.hostname):
            return {"ok": False, "error": "Private, reserved, or unresolved connector hosts are disabled"}
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
