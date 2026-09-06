from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from app.dpn_connector_protocol_v10 import ConnectorAction, ConnectorProtocolError, ConnectorRequest
from app.dpn_sql_connector_v10 import SQLiteConnectorAdapter, SQLiteConnectorProtocolService


def _database(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE secrets (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT INTO projects(id, name, status) VALUES
                ('1', 'Alpha', 'active'),
                ('2', 'Beta', 'paused');
            INSERT INTO secrets(key, value) VALUES ('token', 'never-expose-me');
            """
        )


class _DB:
    def __init__(self, path: Path):
        self.path = path


def test_sql_catalog_is_read_only_and_allowlisted(tmp_path: Path):
    path = tmp_path / "dpn.sqlite3"
    _database(path)
    service = SQLiteConnectorProtocolService(_DB(path))

    catalog = service.catalog()

    assert catalog["ok"] is True
    assert catalog["read_only"] is True
    assert catalog["raw_sql"] is False
    assert "projects" in catalog["allowed_tables"]
    assert "secrets" not in catalog["allowed_tables"]


def test_sql_read_uses_parameterized_filters_and_bounded_limit(tmp_path: Path):
    path = tmp_path / "dpn.sqlite3"
    _database(path)
    service = SQLiteConnectorProtocolService(_DB(path), frozenset({"projects"}))

    result = asyncio.run(
        service.read(
            "projects",
            columns=["id", "name"],
            filters={"status": "active"},
            order_by="id",
            limit=9999,
        )
    )

    assert result["ok"] is True
    assert result["result"]["rows"] == [{"id": "1", "name": "Alpha"}]
    assert result["provenance"]["read_only"] is True
    assert result["provenance"]["parameterized"] is True
    assert result["provenance"]["limit"] == 500


def test_sql_connector_refuses_non_allowlisted_tables(tmp_path: Path):
    path = tmp_path / "dpn.sqlite3"
    _database(path)
    service = SQLiteConnectorProtocolService(_DB(path), frozenset({"projects"}))

    with pytest.raises(ConnectorProtocolError, match="not allow-listed"):
        asyncio.run(service.read("secrets"))


def test_sql_connector_refuses_identifier_injection(tmp_path: Path):
    path = tmp_path / "dpn.sqlite3"
    _database(path)
    service = SQLiteConnectorProtocolService(_DB(path), frozenset({"projects"}))

    with pytest.raises(ConnectorProtocolError, match="identifier is invalid"):
        asyncio.run(service.read('projects; DROP TABLE projects;--'))


def test_sql_connector_refuses_unknown_columns(tmp_path: Path):
    path = tmp_path / "dpn.sqlite3"
    _database(path)
    service = SQLiteConnectorProtocolService(_DB(path), frozenset({"projects"}))

    with pytest.raises(ConnectorProtocolError, match="unknown column"):
        asyncio.run(service.read("projects", columns=["id", "password"]))


def test_sql_adapter_rejects_write_actions_even_when_called_directly(tmp_path: Path):
    path = tmp_path / "dpn.sqlite3"
    _database(path)
    adapter = SQLiteConnectorAdapter(path, frozenset({"projects"}))
    request = ConnectorRequest(
        connector_id="sqlite:dpn-core",
        action=ConnectorAction.UPDATE,
        resource="operational_table",
        payload={"table": "projects"},
        approval_granted=True,
    )

    with pytest.raises(ConnectorProtocolError, match="read/search only"):
        asyncio.run(adapter.execute(request))


def test_sql_connector_health_fails_closed_when_database_missing(tmp_path: Path):
    adapter = SQLiteConnectorAdapter(tmp_path / "missing.sqlite3", frozenset({"projects"}))

    assert asyncio.run(adapter.health()).value == "unavailable"
