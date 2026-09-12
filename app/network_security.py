"""Shared outbound-network validation for SSRF and DNS-rebinding defenses."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse


class NetworkSecurityError(ValueError):
    """Raised when an outbound endpoint violates the network security policy."""


@dataclass(frozen=True)
class ResolvedEndpoint:
    url: str
    host: str
    port: int
    addresses: frozenset[str]
    is_private: bool


def _normalize_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    raw = str(value or "").strip()
    if "%" in raw:
        raise NetworkSecurityError("Scoped IP addresses are not allowed")
    try:
        return ipaddress.ip_address(raw)
    except ValueError as exc:
        raise NetworkSecurityError("Endpoint resolved to an invalid IP address") from exc


def _classify_addresses(addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address]) -> bool:
    if not addresses:
        raise NetworkSecurityError("Endpoint hostname did not resolve")
    private_flags: set[bool] = set()
    for address in addresses:
        if address.is_link_local or address.is_multicast or address.is_reserved or address.is_unspecified:
            raise NetworkSecurityError("Link-local, multicast, reserved, or unspecified addresses are blocked")
        private_flags.add(bool(address.is_private or address.is_loopback))
    if len(private_flags) != 1:
        raise NetworkSecurityError("Mixed public/private DNS answers are blocked")
    return True in private_flags


def resolve_url_endpoint(
    url: str,
    *,
    allow_private: bool = False,
    resolver: Callable[..., Any] | None = None,
) -> ResolvedEndpoint:
    """Resolve an HTTP(S) URL once and return the exact approved address set."""
    value = str(url or "").strip()
    try:
        parsed = urlparse(value)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise NetworkSecurityError("Endpoint URL is invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise NetworkSecurityError("Endpoint must use HTTP or HTTPS")
    if parsed.username or parsed.password:
        raise NetworkSecurityError("Embedded URL credentials are blocked")
    if not 1 <= int(port) <= 65535:
        raise NetworkSecurityError("Endpoint port is invalid")

    host = parsed.hostname.rstrip(".").lower()
    if not host:
        raise NetworkSecurityError("Endpoint hostname is invalid")

    try:
        literal = _normalize_ip(host)
        resolved = {literal}
    except NetworkSecurityError:
        if "%" in host:
            raise
        lookup = resolver or socket.getaddrinfo
        try:
            records = lookup(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise NetworkSecurityError("Endpoint hostname could not be resolved") from exc
        resolved = set()
        for record in records:
            try:
                resolved.add(_normalize_ip(record[4][0]))
            except (IndexError, TypeError) as exc:
                raise NetworkSecurityError("Endpoint resolver returned an invalid address") from exc

    is_private = _classify_addresses(resolved)
    if is_private and not allow_private:
        raise NetworkSecurityError("Private and loopback network addresses are blocked")

    return ResolvedEndpoint(
        url=value,
        host=host,
        port=int(port),
        addresses=frozenset(str(address) for address in resolved),
        is_private=is_private,
    )


def verify_peer_address(peer_address: str, endpoint: ResolvedEndpoint) -> str:
    """Require the connected peer to be one of the addresses approved before connect."""
    peer = _normalize_ip(peer_address)
    _classify_addresses({peer})
    normalized = str(peer)
    if normalized not in endpoint.addresses:
        raise NetworkSecurityError("Connected peer did not match the pre-resolved endpoint")
    return normalized


def httpx_connected_peer(response: Any) -> str | None:
    """Extract the actual server address from HTTPX/httpcore response extensions."""
    stream = getattr(response, "extensions", {}).get("network_stream")
    if stream is None or not hasattr(stream, "get_extra_info"):
        return None
    server_addr = stream.get_extra_info("server_addr")
    if not server_addr:
        return None
    if isinstance(server_addr, (tuple, list)) and server_addr:
        return str(server_addr[0])
    if isinstance(server_addr, dict):
        value = server_addr.get("ipAddress") or server_addr.get("host")
        return str(value) if value else None
    return str(server_addr)


def verify_httpx_response_peer(
    response: Any,
    endpoint: ResolvedEndpoint,
    *,
    require_peer: bool = True,
) -> str | None:
    """Validate the transport peer before a response body is consumed."""
    peer = httpx_connected_peer(response)
    if peer is None:
        if require_peer:
            raise NetworkSecurityError("HTTP transport did not expose the connected peer address")
        return None
    return verify_peer_address(peer, endpoint)


__all__ = [
    "NetworkSecurityError",
    "ResolvedEndpoint",
    "httpx_connected_peer",
    "resolve_url_endpoint",
    "verify_httpx_response_peer",
    "verify_peer_address",
]
