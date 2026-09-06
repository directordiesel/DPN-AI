from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.connectors import ConnectorHub


@dataclass(frozen=True)
class FirstPartyConnectorProfile:
    profile_id: str
    display_name: str
    base_url: str
    allowed_methods: tuple[str, ...]
    headers: dict[str, str]
    secret_names: tuple[str, ...]
    notes: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "base_url": self.base_url,
            "allowed_methods": list(self.allowed_methods),
            "required_secrets": list(self.secret_names),
            "notes": self.notes,
        }


_PROFILES: dict[str, FirstPartyConnectorProfile] = {
    "github": FirstPartyConnectorProfile(
        profile_id="github",
        display_name="GitHub",
        base_url="https://api.github.com/",
        allowed_methods=("GET", "POST", "PUT", "PATCH", "DELETE"),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer {{secret:github.token}}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        secret_names=("github.token",),
        notes="GitHub REST API. Mutating methods remain DPN approval-gated and single-attempt.",
    ),
    "google": FirstPartyConnectorProfile(
        profile_id="google",
        display_name="Google APIs",
        base_url="https://www.googleapis.com/",
        allowed_methods=("GET", "POST", "PUT", "PATCH", "DELETE"),
        headers={"Authorization": "Bearer {{secret:google.access_token}}"},
        secret_names=("google.access_token",),
        notes="Google API root for configured Gmail/Calendar/Drive REST paths. OAuth refresh remains external to this static profile.",
    ),
    "microsoft_graph": FirstPartyConnectorProfile(
        profile_id="microsoft_graph",
        display_name="Microsoft Graph",
        base_url="https://graph.microsoft.com/v1.0/",
        allowed_methods=("GET", "POST", "PUT", "PATCH", "DELETE"),
        headers={"Authorization": "Bearer {{secret:microsoft_graph.access_token}}"},
        secret_names=("microsoft_graph.access_token",),
        notes="Microsoft Graph v1.0 for Outlook, Calendar and OneDrive paths.",
    ),
    "slack": FirstPartyConnectorProfile(
        profile_id="slack",
        display_name="Slack",
        base_url="https://slack.com/api/",
        allowed_methods=("GET", "POST"),
        headers={"Authorization": "Bearer {{secret:slack.bot_token}}"},
        secret_names=("slack.bot_token",),
        notes="Slack Web API. POST operations are treated as create/write and require approval.",
    ),
    "discord": FirstPartyConnectorProfile(
        profile_id="discord",
        display_name="Discord",
        base_url="https://discord.com/api/v10/",
        allowed_methods=("GET", "POST", "PUT", "PATCH", "DELETE"),
        headers={"Authorization": "Bot {{secret:discord.bot_token}}"},
        secret_names=("discord.bot_token",),
        notes="Discord REST API v10. External mutations remain approval-gated.",
    ),
    "reddit": FirstPartyConnectorProfile(
        profile_id="reddit",
        display_name="Reddit OAuth API",
        base_url="https://oauth.reddit.com/",
        allowed_methods=("GET", "POST", "PUT", "PATCH", "DELETE"),
        headers={
            "Authorization": "Bearer {{secret:reddit.access_token}}",
            "User-Agent": "DPN-AI/10.0",
        },
        secret_names=("reddit.access_token",),
        notes="Reddit OAuth API. Token acquisition/refresh is intentionally not performed by this profile.",
    ),
}


class FirstPartyConnectorService:
    """Curated provider profiles layered over the hardened HTTP ConnectorHub.

    Installing a profile stores only secret references, never secret values. The
    caller must place the named secret in SecretVault separately. This operation
    changes local connector configuration and is therefore registered behind an
    explicit human-approval boundary.
    """

    def __init__(self, hub: ConnectorHub) -> None:
        self.hub = hub

    def catalog(self) -> dict[str, Any]:
        return {
            "ok": True,
            "profiles": [_PROFILES[key].public_dict() for key in sorted(_PROFILES)],
        }

    def install(self, profile_id: str, name: str = "", enabled: bool = False) -> dict[str, Any]:
        profile = _PROFILES.get(str(profile_id).strip().lower())
        if profile is None:
            return {"ok": False, "error": "Unknown first-party connector profile"}
        result = self.hub.create(
            name=(name.strip() or profile.display_name),
            base_url=profile.base_url,
            headers=dict(profile.headers),
            allowed_methods=list(profile.allowed_methods),
            enabled=bool(enabled),
        )
        if not result.get("ok"):
            return result
        connector = result.get("connector") or {}
        return {
            "ok": True,
            "profile_id": profile.profile_id,
            "connector_id": connector.get("id"),
            "enabled": bool(connector.get("enabled")),
            "required_secrets": list(profile.secret_names),
        }


__all__ = ["FirstPartyConnectorProfile", "FirstPartyConnectorService"]
