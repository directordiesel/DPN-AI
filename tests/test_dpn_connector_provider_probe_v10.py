from __future__ import annotations

import asyncio

from app.dpn_first_party_connectors_v10 import FirstPartyConnectorService


class FakeVault:
    def __init__(self, names):
        self.names = list(names)

    def list(self):
        return {"ok": True, "secrets": list(self.names)}


class FakeDB:
    def __init__(self, connector):
        self.connector = connector

    def get_connector(self, connector_id):
        if connector_id == self.connector.get("id"):
            return dict(self.connector)
        return None


class FakeHub:
    def __init__(self, connector, response):
        self.db = FakeDB(connector)
        self.response = response
        self.calls = []

    async def request(self, connector_id, **kwargs):
        self.calls.append((connector_id, kwargs))
        return dict(self.response)


def github_connector(**overrides):
    connector = {
        "id": "github-1",
        "kind": "http",
        "enabled": True,
        "config": {
            "base_url": "https://api.github.com/",
            "headers": {
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer {{secret:github.token}}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            "allowed_methods": ["GET", "POST", "PUT", "PATCH", "DELETE"],
        },
    }
    connector.update(overrides)
    return connector


def test_probe_uses_fixed_get_endpoint_and_returns_metadata_only():
    hub = FakeHub(
        github_connector(),
        {
            "ok": True,
            "status_code": 200,
            "url": "https://api.github.com/user",
            "content_type": "application/json",
            "response": {"login": "sensitive-user", "email": "private@example.test"},
        },
    )
    service = FirstPartyConnectorService(hub, FakeVault(["github.token"]))

    result = asyncio.run(service.probe("github", "github-1", timeout_seconds=99))

    assert result == {
        "ok": True,
        "profile_id": "github",
        "connector_id": "github-1",
        "reachable": True,
        "authenticated": True,
        "state": "authenticated",
        "status_code": 200,
    }
    assert hub.calls == [
        (
            "github-1",
            {"method": "GET", "path": "user", "timeout_seconds": 15},
        )
    ]
    assert "sensitive-user" not in repr(result)
    assert "private@example.test" not in repr(result)


def test_probe_rejects_profile_connector_binding_mismatch_before_network():
    connector = github_connector()
    connector["config"] = dict(connector["config"], base_url="https://example.test/")
    hub = FakeHub(connector, {"status_code": 200})
    service = FirstPartyConnectorService(hub, FakeVault(["github.token"]))

    result = asyncio.run(service.probe("github", "github-1"))

    assert result["ok"] is False
    assert "does not match" in result["error"]
    assert hub.calls == []


def test_probe_rejects_tampered_authentication_template_before_network():
    connector = github_connector()
    connector["config"] = dict(connector["config"])
    connector["config"]["headers"] = {"Authorization": "Bearer attacker-value"}
    hub = FakeHub(connector, {"status_code": 200})
    service = FirstPartyConnectorService(hub, FakeVault(["github.token"]))

    result = asyncio.run(service.probe("github", "github-1"))

    assert result["ok"] is False
    assert "authentication configuration" in result["error"]
    assert hub.calls == []


def test_probe_requires_secret_metadata_before_network():
    hub = FakeHub(github_connector(), {"status_code": 200})
    service = FirstPartyConnectorService(hub, FakeVault([]))

    result = asyncio.run(service.probe("github", "github-1"))

    assert result["ok"] is False
    assert result["missing_secrets"] == ["github.token"]
    assert hub.calls == []


def test_probe_reports_rejected_credentials_without_exposing_provider_body():
    hub = FakeHub(
        github_connector(),
        {"ok": False, "status_code": 401, "response": {"message": "token details must not escape"}},
    )
    service = FirstPartyConnectorService(hub, FakeVault(["github.token"]))

    result = asyncio.run(service.probe("github", "github-1"))

    assert result["ok"] is True
    assert result["authenticated"] is False
    assert result["state"] == "rejected"
    assert result["status_code"] == 401
    assert "token details" not in repr(result)


def test_slack_probe_fails_closed_without_posting_auth_test():
    connector = {
        "id": "slack-1",
        "kind": "http",
        "enabled": True,
        "config": {
            "base_url": "https://slack.com/api/",
            "headers": {"Authorization": "Bearer {{secret:slack.bot_token}}"},
            "allowed_methods": ["GET", "POST"],
        },
    }
    hub = FakeHub(connector, {"status_code": 200})
    service = FirstPartyConnectorService(hub, FakeVault(["slack.bot_token"]))

    result = asyncio.run(service.probe("slack", "slack-1"))

    assert result["ok"] is False
    assert "not available" in result["error"]
    assert hub.calls == []
