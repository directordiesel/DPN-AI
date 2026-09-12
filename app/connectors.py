from __future__ import annotations

import ipaddress
import json
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.db import Database
from app.network_security import NetworkSecurityError, resolve_url_endpoint, verify_httpx_response_peer
from app.persistence_security import sanitize_for_persistence
from app.vault import SecretVault


SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"}
MAX_CONNECTOR_RESPONSE_BYTES = 2_000_000
_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_SECRET_HEADER_VALUE = re.compile(
    r"(?i)^(?:(?:bearer|basic)\s+)?\{\{secret:[A-Za-z0-9_.-]{1,100}\}\}$"
)
_SENSITIVE_HEADER_PARTS = ("authorization", "cookie", "token", "secret", "api-key", "apikey", "credential")


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
    def _validated_headers(headers: dict[str, str] | None) -> tuple[bool, dict[str, str] | str]:
        safe: dict[str, str] = {}
        for raw_name, raw_value in (headers or {}).items():
            name = str(raw_name).strip()
            value = str(raw_value).strip()
            if not name or len(name) > 200 or not _HEADER_NAME.fullmatch(name):
                return False, "Connector header name is invalid"
            if len(value) > 8000 or any(ch in value for ch in ("\r", "\n", "\x00")):
                return False, f"Connector header {name} contains an invalid or oversized value"
            normalized = name.lower()
            if any(part in normalized for part in _SENSITIVE_HEADER_PARTS) and not _SECRET_HEADER_VALUE.fullmatch(value):
                return False, f"Sensitive connector header {name} must use an encrypted {{secret:NAME}} reference"
            safe[name] = value
        return True, safe

    @staticmethod
    def _is_private_host(host: str) -> bool:
        """Fail closed: unresolved or non-public hosts are unsafe for public-only connectors."""
        try:
            addresses = socket.getaddrinfo(host, None)
        except OSError:
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
        try:
            resolve_url_endpoint(base_url, allow_private=self.allow_private_network)
        except NetworkSecurityError as exc:
            return False, str(exc)
        return True, ""

    def create(self, name: str, base_url: str, headers: dict[str, str] | None = None,
               allowed_methods: list[str] | None = None, enabled: bool = True) -> dict[str, Any]:
        valid, reason = self._validate_base_url(base_url)
        if not valid:
            return {"ok": False, "error": reason}
        methods_ok, methods = self._normalized_methods(allowed_methods)
        if not methods_ok:
            return {"ok": False, "error": methods}
        headers_ok, safe_headers = self._validated_headers(headers)
        if not headers_ok:
            return {"ok": False, "error": safe_headers}
        config = {
            "base_url": base_url.rstrip("/") + "/",
            "headers": safe_headers,
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
        try:
            endpoint = resolve_url_endpoint(url, allow_private=self.allow_private_network)
        except NetworkSecurityError as exc:
            return {"ok": False, "error": str(exc)}
        try:
            headers = self.vault.resolve(config.get("headers", {}))
            body = self.vault.resolve(json_body)
            timeout = max(5, min(timeout_seconds, 120))
            async with httpx.AsyncClient(trust_env=False, timeout=timeout, follow_redirects=False) as client:
                async with client.stream(method, url, params=params, json=body, headers=headers) as response:
                    verify_httpx_response_peer(response, endpoint)
                    content_length = int(response.headers.get("content-length", "0") or 0)
                    if content_length > MAX_CONNECTOR_RESPONSE_BYTES:
                        return {"ok": False, "error": "Connector response exceeded the 2 MB safety limit"}
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_CONNECTOR_RESPONSE_BYTES:
                            return {"ok": False, "error": "Connector response exceeded the 2 MB safety limit"}
                    status_code = response.status_code
                    response_url = str(response.url)
                    content_type = response.headers.get("content-type", "")
                    encoding = response.encoding or "utf-8"

            text = bytes(raw).decode(encoding, errors="replace")
            parsed: Any = text[:100_000]
            if "json" in content_type:
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = text[:100_000]
            parsed = sanitize_for_persistence(parsed)
            return {
                "ok": status_code < 400,
                "status_code": status_code,
                "url": response_url,
                "content_type": content_type,
                "response": parsed,
            }
        except (httpx.HTTPError, OSError, ValueError, KeyError) as exc:
            detail = str(sanitize_for_persistence(str(exc)))
            return {"ok": False, "error": f"Connector request failed: {type(exc).__name__}: {detail}"}
