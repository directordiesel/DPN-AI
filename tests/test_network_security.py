import socket

import httpx
import pytest

from app.network_security import (
    NetworkSecurityError,
    resolve_url_endpoint,
    verify_httpx_response_peer,
    verify_peer_address,
)


def _resolver(*addresses: str):
    def resolve(host, port, *, type=socket.SOCK_STREAM):
        del host, type
        return [
            (socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
            for address in addresses
        ]
    return resolve


def test_public_endpoint_resolution_returns_exact_approved_set():
    endpoint = resolve_url_endpoint(
        "https://example.test/resource",
        resolver=_resolver("8.8.8.8", "1.1.1.1"),
    )
    assert endpoint.addresses == frozenset({"8.8.8.8", "1.1.1.1"})
    assert endpoint.is_private is False


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.8", "169.254.169.254", "::1", "fe80::1"])
def test_public_endpoint_resolution_blocks_non_public_addresses(address: str):
    with pytest.raises(NetworkSecurityError):
        resolve_url_endpoint("https://example.test", resolver=_resolver(address))


def test_mixed_public_private_dns_answers_fail_closed():
    with pytest.raises(NetworkSecurityError, match="Mixed public/private"):
        resolve_url_endpoint(
            "https://example.test",
            resolver=_resolver("8.8.8.8", "10.0.0.7"),
        )


def test_private_network_mode_allows_private_but_not_link_local():
    endpoint = resolve_url_endpoint(
        "http://internal.test:8080",
        allow_private=True,
        resolver=_resolver("10.0.0.7"),
    )
    assert endpoint.is_private is True
    with pytest.raises(NetworkSecurityError, match="Link-local"):
        resolve_url_endpoint(
            "http://metadata.test",
            allow_private=True,
            resolver=_resolver("169.254.169.254"),
        )


class _Stream:
    def __init__(self, peer):
        self.peer = peer

    def get_extra_info(self, name):
        return self.peer if name == "server_addr" else None


def test_httpx_peer_must_match_pre_resolved_dns_set():
    endpoint = resolve_url_endpoint(
        "https://example.test",
        resolver=_resolver("8.8.8.8"),
    )
    response = httpx.Response(
        200,
        extensions={"network_stream": _Stream(("8.8.8.8", 443))},
    )
    assert verify_httpx_response_peer(response, endpoint) == "8.8.8.8"

    rebound = httpx.Response(
        200,
        extensions={"network_stream": _Stream(("10.0.0.7", 443))},
    )
    with pytest.raises(NetworkSecurityError):
        verify_httpx_response_peer(rebound, endpoint)


def test_peer_verification_rejects_unexpected_public_address_too():
    endpoint = resolve_url_endpoint(
        "https://example.test",
        resolver=_resolver("8.8.8.8"),
    )
    with pytest.raises(NetworkSecurityError, match="pre-resolved"):
        verify_peer_address("1.1.1.1", endpoint)
