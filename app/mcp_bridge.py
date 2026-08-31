from __future__ import annotations

import ipaddress
import json
import re
import shutil
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlparse

from app.db import Database
from app.vault import SecretVault


class MCPBridge:
    """Optional Model Context Protocol client with deny-by-default tool allowlists.

    The stable v1 Python SDK is loaded only when the operator installs the
    optional MCP requirements. Server processes and remote calls are never
    started merely by listing configuration.
    """

    def __init__(self, db: Database, vault: SecretVault | None = None, allow_external: bool = False):
        self.db = db
        self.vault = vault
        self.allow_external = allow_external

    @staticmethod
    def status() -> dict[str, Any]:
        try:
            import mcp  # noqa: F401
            available = True
        except Exception:
            available = False
        return {
            "ok": True,
            "available": available,
            "install": "pip install -r requirements-mcp.txt",
            "stable_sdk_constraint": "mcp>=1.28,<2",
            "configured_servers": None,
        }

    @staticmethod
    def _host_scope(host: str) -> str:
        normalized = host.strip("[]").lower()
        if normalized in {"localhost", "127.0.0.1", "::1"}:
            return "loopback"
        try:
            address = ipaddress.ip_address(normalized)
            if address.is_loopback:
                return "loopback"
            if address.is_private or address.is_link_local:
                return "private"
            return "public"
        except ValueError:
            try:
                addresses = socket.getaddrinfo(normalized, None)
            except OSError:
                return "unknown"
            scopes = {MCPBridge._host_scope(item[4][0]) for item in addresses}
            if scopes == {"loopback"}:
                return "loopback"
            if scopes <= {"loopback", "private"}:
                return "private"
            return "public"

    def create_server(self, name: str, transport: str, command: str | None = None,
                      args: list[str] | None = None, url: str | None = None,
                      env: dict[str, str] | None = None, allowed_tools: list[str] | None = None,
                      enabled: bool = True) -> dict[str, Any]:
        transport = transport.strip().lower()
        if transport not in {"stdio", "http"}:
            return {"ok": False, "error": "MCP transport must be stdio or http"}
        if allowed_tools:
            return {"ok": False, "error": "New MCP servers must start with an empty allowlist. Discover tools before approving names."}
        config: dict[str, Any]
        if transport == "stdio":
            if not command or not command.strip():
                return {"ok": False, "error": "stdio MCP servers require an executable command"}
            safe_env: dict[str, str] = {}
            for key, value in (env or {}).items():
                key_text, value_text = str(key)[:200], str(value)[:4000]
                if any(token in key_text.upper() for token in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "PRIVATE_KEY")) and not re.fullmatch(r"\{\{secret:[A-Za-z0-9_.-]{1,100}\}\}", value_text):
                    return {"ok": False, "error": f"Sensitive MCP environment value {key_text} must use an encrypted {{secret:NAME}} reference"}
                safe_env[key_text] = value_text
            config = {"command": command.strip(), "args": [str(item) for item in (args or [])[:100]], "env": safe_env}
        else:
            parsed = urlparse(str(url or ""))
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                return {"ok": False, "error": "HTTP MCP server URL must use http or https"}
            scope = self._host_scope(parsed.hostname)
            if scope != "loopback" and not self.allow_external:
                return {"ok": False, "error": "Non-loopback MCP servers are disabled by default"}
            if scope == "unknown":
                return {"ok": False, "error": "Unable to resolve MCP server host"}
            config = {"url": str(url).rstrip("/")}
        server = self.db.create_mcp_server(name, transport, config, allowed_tools or [], enabled)
        return {"ok": True, "server": self._redact(server)}

    @staticmethod
    def _redact(server: dict[str, Any]) -> dict[str, Any]:
        item = dict(server)
        config = dict(item.get("config") or {})
        if config.get("env"):
            config["env"] = {key: "[configured]" for key in config["env"]}
        item["config"] = config
        return item

    def list_servers(self) -> dict[str, Any]:
        return {"ok": True, "servers": [self._redact(item) for item in self.db.list_mcp_servers()]}

    def update_server(self, server_id: str, *, name: str | None = None, allowed_tools: list[str] | None = None, enabled: bool | None = None) -> dict[str, Any]:
        server = self.db.get_mcp_server(server_id)
        if not server:
            return {"ok": False, "error": "MCP server not found"}
        if allowed_tools is not None:
            discovered = {str(item.get("name")) for item in server.get("tools", []) if isinstance(item, dict) and item.get("name")}
            if allowed_tools and not discovered:
                return {"ok": False, "error": "Discover tools before saving a non-empty allowlist"}
            unknown = sorted({str(item) for item in allowed_tools} - discovered)
            if unknown:
                return {"ok": False, "error": f"Allowlist contains tools that were not discovered: {', '.join(unknown[:20])}"}
        updated = self.db.update_mcp_server(server_id, name=name, allowed_tools=allowed_tools, enabled=enabled)
        return {"ok": True, "server": self._redact(updated or {})}

    def delete_server(self, server_id: str) -> dict[str, Any]:
        if not self.db.delete_mcp_server(server_id):
            return {"ok": False, "error": "MCP server not found"}
        return {"ok": True, "deleted": server_id}

    @asynccontextmanager
    async def _session(self, server: dict[str, Any]) -> AsyncIterator[Any]:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except Exception as exc:
            raise RuntimeError("MCP SDK is not installed. Use requirements-mcp.txt.") from exc
        config = server.get("config") or {}
        if server["transport"] == "stdio":
            command = str(config.get("command") or "")
            if not shutil.which(command) and not Path(command).is_file():
                raise RuntimeError(f"MCP executable was not found: {command}")
            params = StdioServerParameters(
                command=command,
                args=[str(item) for item in config.get("args", [])],
                env={str(key): str(value) for key, value in ((self.vault.resolve(config.get("env") or {})) if self.vault else (config.get("env") or {})).items()} or None,
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
            return
        try:
            from mcp.client.streamable_http import streamablehttp_client
        except Exception as exc:
            raise RuntimeError("Installed MCP SDK does not provide Streamable HTTP support.") from exc
        async with streamablehttp_client(str(config.get("url"))) as transport:
            read, write = transport[0], transport[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    @staticmethod
    def _serialize(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, list):
            return [MCPBridge._serialize(item) for item in value]
        if isinstance(value, dict):
            return {str(key): MCPBridge._serialize(item) for key, item in value.items()}
        try:
            json.dumps(value)
            return value
        except Exception:
            return str(value)

    async def discover(self, server_id: str) -> dict[str, Any]:
        server = self.db.get_mcp_server(server_id)
        if not server or not server.get("enabled"):
            return {"ok": False, "error": "MCP server not found or disabled"}
        try:
            async with self._session(server) as session:
                response = await session.list_tools()
            tools = []
            for tool in getattr(response, "tools", []) or []:
                item = self._serialize(tool)
                name = str(item.get("name") or "") if isinstance(item, dict) else ""
                if name:
                    tools.append(item)
            self.db.cache_mcp_tools(server_id, tools)
            allowed = set(server.get("allowed_tools") or [])
            return {
                "ok": True, "server_id": server_id, "tool_count": len(tools),
                "tools": [{**item, "allowed": item.get("name") in allowed} for item in tools],
            }
        except Exception as exc:
            return {"ok": False, "error": f"MCP discovery failed: {type(exc).__name__}: {exc}"}

    async def call_tool(self, server_id: str, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        server = self.db.get_mcp_server(server_id)
        if not server or not server.get("enabled"):
            return {"ok": False, "error": "MCP server not found or disabled"}
        allowed = set(server.get("allowed_tools") or [])
        if tool_name not in allowed:
            return {"ok": False, "error": "MCP tool is not in this server's allowlist"}
        try:
            async with self._session(server) as session:
                response = await session.call_tool(tool_name, arguments or {})
            payload = self._serialize(response)
            self.db.record_mcp_call(server_id, tool_name, arguments or {}, payload, True)
            return {"ok": True, "server_id": server_id, "tool": tool_name, "result": payload}
        except Exception as exc:
            error = f"MCP tool call failed: {type(exc).__name__}: {exc}"
            self.db.record_mcp_call(server_id, tool_name, arguments or {}, {"error": error}, False)
            return {"ok": False, "error": error}