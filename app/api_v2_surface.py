from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from app.api_v2_contracts import API_V2_VERSION, APIV2ContractError, negotiate_capabilities


DEFAULT_API_V2_CAPABILITIES: tuple[str, ...] = (
    "protocol.capabilities",
    "protocol.cursor",
    "protocol.envelopes",
    "protocol.sequence",
)


@dataclass(frozen=True)
class APIV2Readiness:
    protocol_version: str
    transport: str
    live: bool
    authenticated_mount_required: bool
    capabilities: tuple[str, ...]
    limitations: tuple[str, ...]


def build_readiness(
    *,
    supported: Iterable[str] = DEFAULT_API_V2_CAPABILITIES,
    transport: str = "contract-only",
    live: bool = False,
) -> APIV2Readiness:
    transport_value = str(transport or "").strip().lower()
    if transport_value not in {"contract-only", "rest-readonly", "websocket"}:
        raise APIV2ContractError("unsupported API v2 transport declaration")
    if transport_value == "websocket" and not live:
        limitations = ("websocket transport is not mounted",)
    elif transport_value == "contract-only":
        limitations = ("protocol contracts are available but no API v2 transport is mounted",)
    else:
        limitations = ()

    normalized = negotiate_capabilities((), supported).supported
    return APIV2Readiness(
        protocol_version=API_V2_VERSION,
        transport=transport_value,
        live=bool(live),
        authenticated_mount_required=True,
        capabilities=normalized,
        limitations=limitations,
    )


def readiness_payload(readiness: APIV2Readiness | None = None) -> dict[str, object]:
    value = readiness or build_readiness()
    if not isinstance(value, APIV2Readiness):
        raise APIV2ContractError("readiness value must be APIV2Readiness")
    return asdict(value)


def negotiate_client(
    requested: Iterable[str],
    *,
    supported: Iterable[str] = DEFAULT_API_V2_CAPABILITIES,
) -> dict[str, object]:
    result = negotiate_capabilities(requested, supported)
    return {
        "protocol_version": API_V2_VERSION,
        "accepted": result.accepted,
        "rejected": result.rejected,
        "supported": result.supported,
        "compatible": not result.rejected,
    }


__all__ = [
    "APIV2Readiness",
    "DEFAULT_API_V2_CAPABILITIES",
    "build_readiness",
    "negotiate_client",
    "readiness_payload",
]
