from __future__ import annotations

from app.dpn_first_party_connectors_v10 import FirstPartyConnectorService


class FakeHub:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "ok": True,
            "connector": {
                "id": "connector-1",
                "enabled": kwargs["enabled"],
            },
        }


class FakeVault:
    def __init__(self, names=None, fail=False) -> None:
        self.names = sorted(names or [])
        self.fail = fail
        self.get_calls = []

    def list(self):
        if self.fail:
            raise ValueError("corrupt vault")
        return {"ok": True, "secrets": list(self.names)}

    def get_value(self, name):
        self.get_calls.append(name)
        raise AssertionError("readiness must never decrypt credential values")


def test_catalog_exposes_only_secret_names_not_secret_values():
    service = FirstPartyConnectorService(FakeHub())

    result = service.catalog()

    assert result["ok"] is True
    ids = [item["profile_id"] for item in result["profiles"]]
    assert ids == sorted(ids)
    assert {"github", "google", "microsoft_graph", "slack", "discord", "reddit"} <= set(ids)
    rendered = str(result)
    assert "{{secret:" not in rendered
    assert "Bearer {{" not in rendered
    assert "github.token" in rendered


def test_readiness_uses_secret_metadata_only_and_reports_missing_names():
    vault = FakeVault({"github.token", "slack.bot_token"})
    service = FirstPartyConnectorService(FakeHub(), vault)

    result = service.readiness()

    assert result["ok"] is True
    assert result["profile_count"] == 6
    assert result["ready_count"] == 2
    by_id = {item["profile_id"]: item for item in result["profiles"]}
    assert by_id["github"] == {"profile_id": "github", "ready": True, "missing_secrets": []}
    assert by_id["google"] == {
        "profile_id": "google",
        "ready": False,
        "missing_secrets": ["google.access_token"],
    }
    assert vault.get_calls == []


def test_readiness_fails_closed_when_vault_is_unavailable():
    service = FirstPartyConnectorService(FakeHub(), FakeVault(fail=True))

    result = service.readiness()

    assert result == {
        "ok": False,
        "error": "Secret vault unavailable; first-party connector readiness cannot be verified",
        "ready_count": 0,
        "profiles": [],
    }


def test_github_profile_installs_vault_reference_and_disabled_by_default():
    hub = FakeHub()
    service = FirstPartyConnectorService(hub)

    result = service.install("github")

    assert result == {
        "ok": True,
        "profile_id": "github",
        "connector_id": "connector-1",
        "enabled": False,
        "required_secrets": ["github.token"],
    }
    assert hub.calls == [
        {
            "name": "GitHub",
            "base_url": "https://api.github.com/",
            "headers": {
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer {{secret:github.token}}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            "allowed_methods": ["GET", "POST", "PUT", "PATCH", "DELETE"],
            "enabled": False,
        }
    ]


def test_unknown_profile_fails_closed_without_connector_creation():
    hub = FakeHub()
    service = FirstPartyConnectorService(hub)

    result = service.install("not-a-provider")

    assert result == {"ok": False, "error": "Unknown first-party connector profile"}
    assert hub.calls == []


def test_profiles_do_not_embed_credentials():
    service = FirstPartyConnectorService(FakeHub())
    catalog = service.catalog()["profiles"]

    for profile in catalog:
        assert profile["base_url"].startswith("https://")
        assert all("token" not in profile["base_url"].lower() for _ in [0])
        assert profile["required_secrets"]
