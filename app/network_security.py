"""Shared outbound-network validation for SSRF and DNS-rebinding defenses."""

from __future__ import annotations

import ipaddress
import socket

import httpx
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
        address = ipaddress.ip_address(raw)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            return address.ipv4_mapped
        return address
    except ValueError as exc:
        raise NetworkSecurityError("Endpoint resolved to an invalid IP address") from exc


def _classify_addresses(addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address]) -> bool:
    if not addresses:
        raise NetworkSecurityError("Endpoint hostname did not resolve")
    private_flags: set[bool] = set()
    for address in addresses:
        if address.is_link_local or address.is_multicast or address.is_reserved or address.is_unspecified:
            raise NetworkSecurityError("Link-local, multicast, reserved, or unspecified addresses are blocked")
        is_private = bool(address.is_private or address.is_loopback)
        if not is_private and not address.is_global:
            raise NetworkSecurityError("Non-global special-purpose network addresses are blocked")
        private_flags.add(is_private)
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


def _preferred_endpoint_address(endpoint: ResolvedEndpoint) -> str:
    addresses = [_normalize_ip(value) for value in endpoint.addresses]
    if not addresses:
        raise NetworkSecurityError("Endpoint has no approved addresses")
    selected = sorted(addresses, key=lambda address: (address.version != 4, int(address)))[0]
    return str(selected)


def _ascii_host(host: str) -> str:
    try:
        return str(host).encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise NetworkSecurityError("Endpoint hostname is not valid IDNA") from exc


def _host_header_value(endpoint: ResolvedEndpoint, scheme: str) -> str:
    host = _ascii_host(endpoint.host)
    rendered = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    return rendered if endpoint.port == default_port else f"{rendered}:{endpoint.port}"


class PinnedAsyncHTTPTransport(httpx.AsyncBaseTransport):
    """Connect HTTPX only to an address approved by the pre-connect resolver."""

    def __init__(
        self,
        endpoint: ResolvedEndpoint,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.address = _preferred_endpoint_address(endpoint)
        self._transport = transport or httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        expected = urlparse(self.endpoint.url)
        request_host = str(request.url.host or "").rstrip(".").lower()
        request_port = request.url.port or (443 if request.url.scheme == "https" else 80)
        if (
            request.url.scheme != expected.scheme
            or request_host != self.endpoint.host
            or int(request_port) != self.endpoint.port
        ):
            raise NetworkSecurityError("Pinned HTTP request does not match the approved endpoint")

        extensions = dict(request.extensions)
        if request.url.scheme == "https":
            extensions["sni_hostname"] = _ascii_host(self.endpoint.host)

        headers = [
            (name, value)
            for name, value in request.headers.raw
            if name.lower() != b"host"
        ]
        headers.append(
            (
                b"host",
                _host_header_value(self.endpoint, request.url.scheme).encode("ascii"),
            )
        )
        pinned_request = httpx.Request(
            method=request.method,
            url=request.url.copy_with(host=self.address),
            headers=headers,
            stream=request.stream,
            extensions=extensions,
        )
        return await self._transport.handle_async_request(pinned_request)

    async def aclose(self) -> None:
        await self._transport.aclose()


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
    "PinnedAsyncHTTPTransport",
    "ResolvedEndpoint",
    "httpx_connected_peer",
    "resolve_url_endpoint",
    "verify_httpx_response_peer",
    "verify_peer_address",
]
