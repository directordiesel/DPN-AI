from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.connectors import ConnectorHub
from app.vault import SecretVault


@dataclass(frozen=True)
class FirstPartyConnectorProfile:
    profile_id: str
    display_name: str
    base_url: str
    allowed_methods: tuple[str, ...]
    headers: dict[str, str]
    secret_names: tuple[str, ...]
    notes: str
    probe_path: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "base_url": self.base_url,
            "allowed_methods": list(self.allowed_methods),
            "required_secrets": list(self.secret_names),
            "remote_probe_supported": self.probe_path is not None,
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
        probe_path="user",
    ),
    "google": FirstPartyConnectorProfile(
        profile_id="google",
        display_name="Google APIs",
        base_url="https://www.googleapis.com/",
        allowed_methods=("GET", "POST", "PUT", "PATCH", "DELETE"),
        headers={"Authorization": "Bearer {{secret:google.access_token}}"},
        secret_names=("google.access_token",),
        notes="Google API root for configured Gmail/Calendar/Drive REST paths. OAuth refresh remains external to this static profile.",
        probe_path="oauth2/v3/userinfo",
    ),
    "microsoft_graph": FirstPartyConnectorProfile(
        profile_id="microsoft_graph",
        display_name="Microsoft Graph",
        base_url="https://graph.microsoft.com/v1.0/",
        allowed_methods=("GET", "POST", "PUT", "PATCH", "DELETE"),
        headers={"Authorization": "Bearer {{secret:microsoft_graph.access_token}}"},
        secret_names=("microsoft_graph.access_token",),
        notes="Microsoft Graph v1.0 for Outlook, Calendar and OneDrive paths.",
        probe_path="me",
    ),
    "slack": FirstPartyConnectorProfile(
        profile_id="slack",
        display_name="Slack",
        base_url="https://slack.com/api/",
        allowed_methods=("GET", "POST"),
        headers={"Authorization": "Bearer {{secret:slack.bot_token}}"},
        secret_names=("slack.bot_token",),
        notes="Slack Web API. POST operations are treated as create/write and require approval; remote auth probing is disabled because the canonical auth.test probe is POST-based.",
    ),
    "discord": FirstPartyConnectorProfile(
        profile_id="discord",
        display_name="Discord",
        base_url="https://discord.com/api/v10/",
        allowed_methods=("GET", "POST", "PUT", "PATCH", "DELETE"),
        headers={"Authorization": "Bot {{secret:discord.bot_token}}"},
        secret_names=("discord.bot_token",),
        notes="Discord REST API v10. External mutations remain approval-gated.",
        probe_path="users/@me",
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
        probe_path="api/v1/me",
    ),
}


class FirstPartyConnectorService:
    """Curated provider profiles layered over the hardened HTTP ConnectorHub."""

    def __init__(self, hub: ConnectorHub, vault: SecretVault | None = None) -> None:
        self.hub = hub
        self.vault = vault or getattr(hub, "vault", None)

    def catalog(self) -> dict[str, Any]:
        return {
            "ok": True,
            "profiles": [_PROFILES[key].public_dict() for key in sorted(_PROFILES)],
        }

    def readiness(self) -> dict[str, Any]:
        """Return secret-safe local readiness without contacting external providers.

        Readiness is intentionally conservative: a profile is never reported ready
        unless every required secret name exists in the configured SecretVault.
        Secret values are not decrypted or returned by this operation.
        """
        if self.vault is None:
            return {
                "ok": False,
                "error": "Secret vault unavailable; first-party connector readiness cannot be verified",
                "ready_count": 0,
                "profiles": [],
            }
        try:
            listed = self.vault.list()
            available = set(listed.get("secrets", [])) if listed.get("ok") else set()
        except Exception:
            return {
                "ok": False,
                "error": "Secret vault unavailable; first-party connector readiness cannot be verified",
                "ready_count": 0,
                "profiles": [],
            }

        profiles: list[dict[str, Any]] = []
        ready_count = 0
        for key in sorted(_PROFILES):
            profile = _PROFILES[key]
            missing = [name for name in profile.secret_names if name not in available]
            ready = not missing
            ready_count += int(ready)
            profiles.append(
                {
                    "profile_id": profile.profile_id,
                    "ready": ready,
                    "missing_secrets": missing,
                }
            )
        return {
            "ok": True,
            "ready_count": ready_count,
            "profile_count": len(profiles),
            "profiles": profiles,
        }

    async def probe(self, profile_id: str, connector_id: str, timeout_seconds: int = 10) -> dict[str, Any]:
        """Perform one bounded, GET-only provider authentication probe.

        The configured connector must still exactly match the curated profile's base
        URL, headers and GET permission. Responses are reduced to status metadata so
        identity data, provider payloads and credentials never leave this boundary.
        """
        profile = _PROFILES.get(str(profile_id).strip().lower())
        if profile is None:
            return {"ok": False, "error": "Unknown first-party connector profile"}
        if profile.probe_path is None:
            return {
                "ok": False,
                "profile_id": profile.profile_id,
                "connector_id": str(connector_id),
                "error": "Remote authentication probe is not available for this profile",
            }
        if self.vault is None:
            return {"ok": False, "error": "Secret vault unavailable; provider probe refused"}
        try:
            listed = self.vault.list()
            available = set(listed.get("secrets", [])) if listed.get("ok") else set()
        except Exception:
            return {"ok": False, "error": "Secret vault unavailable; provider probe refused"}
        missing = [name for name in profile.secret_names if name not in available]
        if missing:
            return {
                "ok": False,
                "profile_id": profile.profile_id,
                "connector_id": str(connector_id),
                "error": "Required provider credentials are not configured",
                "missing_secrets": missing,
            }

        db = getattr(self.hub, "db", None)
        connector = db.get_connector(str(connector_id)) if db is not None else None
        if not connector or connector.get("kind") != "http" or not connector.get("enabled"):
            return {"ok": False, "error": "Connector not found, disabled, or not HTTP"}
        config = connector.get("config") or {}
        configured_base = str(config.get("base_url") or "").rstrip("/") + "/"
        if configured_base != profile.base_url:
            return {"ok": False, "error": "Connector does not match the requested curated provider profile"}
        configured_headers = config.get("headers") or {}
        if configured_headers != profile.headers:
            return {"ok": False, "error": "Connector authentication configuration does not match the curated provider profile"}
        configured_methods = {str(method).upper() for method in config.get("allowed_methods", [])}
        if "GET" not in configured_methods:
            return {"ok": False, "error": "Connector does not permit the safe GET authentication probe"}

        result = await self.hub.request(
            str(connector_id),
            method="GET",
            path=profile.probe_path,
            timeout_seconds=max(5, min(int(timeout_seconds), 15)),
        )
        status_code = result.get("status_code")
        if status_code is None:
            return {
                "ok": False,
                "profile_id": profile.profile_id,
                "connector_id": str(connector_id),
                "error": "Provider authentication probe failed before an HTTP response",
            }
        status_code = int(status_code)
        authenticated = 200 <= status_code < 300
        if authenticated:
            state = "authenticated"
        elif status_code in {401, 403}:
            state = "rejected"
        else:
            state = "provider_error"
        return {
            "ok": True,
            "profile_id": profile.profile_id,
            "connector_id": str(connector_id),
            "reachable": True,
            "authenticated": authenticated,
            "state": state,
            "status_code": status_code,
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
