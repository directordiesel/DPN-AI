from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from app.dpn_connector_protocol_v10 import (
    ConnectorAction,
    ConnectorCapability,
    ConnectorEvidence,
    ConnectorHealth,
    ConnectorManifest,
    ConnectorProtocolError,
    ConnectorRequest,
    ConnectorRisk,
    DPNConnectorRegistry,
)


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DEFAULT_TABLE_ALLOWLIST = frozenset(
    {
        "projects",
        "project_tasks",
        "operation_runs",
        "audit_events",
        "automations",
    }
)


class SQLiteConnectorAdapter:
    """Read-only, parameterized access to explicitly allow-listed DPN operational tables.

    This adapter never accepts raw SQL. Callers select a table, columns, equality filters,
    ordering, and a bounded row limit. Identifiers must exist in the live schema and all
    values are parameterized. The database is opened with SQLite mode=ro for execution.
    """

    kind = "sqlite"

    def __init__(self, path: Path, allowed_tables: frozenset[str] = _DEFAULT_TABLE_ALLOWLIST) -> None:
        self.path = Path(path)
        self.allowed_tables = frozenset(str(item) for item in allowed_tables)

    def _connect_ro(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self.path.resolve().as_posix()}?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @staticmethod
    def _identifier(value: str) -> str:
        candidate = str(value or "").strip()
        if not _IDENTIFIER.fullmatch(candidate):
            raise ConnectorProtocolError("SQL connector identifier is invalid")
        return candidate

    def _schema(self, connection: sqlite3.Connection, table: str) -> list[str]:
        if table not in self.allowed_tables:
            raise ConnectorProtocolError("SQL connector table is not allow-listed")
        rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        columns = [str(row[1]) for row in rows]
        if not columns:
            raise ConnectorProtocolError("SQL connector table is unavailable")
        return columns

    async def health(self) -> ConnectorHealth:
        if not self.path.is_file():
            return ConnectorHealth.UNAVAILABLE
        try:
            with self._connect_ro() as connection:
                result = connection.execute("PRAGMA quick_check").fetchone()
            return ConnectorHealth.HEALTHY if result and str(result[0]).lower() == "ok" else ConnectorHealth.DEGRADED
        except Exception:
            return ConnectorHealth.UNAVAILABLE

    async def execute(self, request: ConnectorRequest) -> ConnectorEvidence:
        if request.action not in {ConnectorAction.READ, ConnectorAction.SEARCH}:
            raise ConnectorProtocolError("SQLite connector supports read/search only")
        payload = dict(request.payload or {})
        table = self._identifier(payload.get("table", ""))
        limit = max(1, min(int(payload.get("limit", 100)), 500))
        filters = payload.get("filters") or {}
        if not isinstance(filters, dict) or len(filters) > 20:
            raise ConnectorProtocolError("SQL connector filters must be an object with at most 20 entries")

        with self._connect_ro() as connection:
            schema = self._schema(connection, table)
            requested_columns = payload.get("columns") or schema
            if not isinstance(requested_columns, list) or not requested_columns or len(requested_columns) > 50:
                raise ConnectorProtocolError("SQL connector columns must be a non-empty list of at most 50 entries")
            columns = [self._identifier(item) for item in requested_columns]
            if any(item not in schema for item in columns):
                raise ConnectorProtocolError("SQL connector requested an unknown column")

            clauses: list[str] = []
            values: list[Any] = []
            for raw_key, value in filters.items():
                key = self._identifier(raw_key)
                if key not in schema:
                    raise ConnectorProtocolError("SQL connector filter references an unknown column")
                clauses.append(f'"{key}" = ?')
                values.append(value)

            order_by = payload.get("order_by")
            order_direction = str(payload.get("order_direction", "ASC")).upper()
            order_sql = ""
            if order_by:
                order_column = self._identifier(order_by)
                if order_column not in schema:
                    raise ConnectorProtocolError("SQL connector order_by references an unknown column")
                if order_direction not in {"ASC", "DESC"}:
                    raise ConnectorProtocolError("SQL connector order_direction must be ASC or DESC")
                order_sql = f' ORDER BY "{order_column}" {order_direction}'

            column_sql = ", ".join(f'"{item}"' for item in columns)
            where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            sql = f'SELECT {column_sql} FROM "{table}"{where_sql}{order_sql} LIMIT ?'
            rows = connection.execute(sql, (*values, limit)).fetchall()

        result_rows = [dict(row) for row in rows]
        return ConnectorEvidence(
            connector_id=request.connector_id,
            action=request.action,
            resource=request.resource,
            provider_kind=self.kind,
            ok=True,
            health=ConnectorHealth.HEALTHY,
            result={"table": table, "row_count": len(result_rows), "rows": result_rows},
            provenance={
                "provider": "sqlite",
                "database": self.path.name,
                "table": table,
                "read_only": True,
                "parameterized": True,
                "limit": limit,
            },
        )


class SQLiteConnectorProtocolService:
    CONNECTOR_ID = "sqlite:dpn-core"

    def __init__(self, database: Any, allowed_tables: frozenset[str] = _DEFAULT_TABLE_ALLOWLIST) -> None:
        self.database = database
        self.allowed_tables = allowed_tables

    def _path(self) -> Path | None:
        value = getattr(self.database, "path", None)
        return Path(value) if value else None

    def registry(self) -> DPNConnectorRegistry:
        registry = DPNConnectorRegistry()
        path = self._path()
        configured = path is not None
        adapter = SQLiteConnectorAdapter(path or Path("__dpn_unconfigured__.sqlite3"), self.allowed_tables)
        manifest = ConnectorManifest(
            connector_id=self.CONNECTOR_ID,
            kind="sqlite",
            display_name="DPN AI Local SQLite",
            capabilities=(
                ConnectorCapability(ConnectorAction.READ, "operational_table", ConnectorRisk.READ_ONLY, False),
                ConnectorCapability(ConnectorAction.SEARCH, "operational_table", ConnectorRisk.READ_ONLY, False),
            ),
            configured=configured,
            enabled=configured,
            local=True,
            metadata={"raw_sql": False, "read_only": True, "allowed_tables": sorted(self.allowed_tables)},
        )
        registry.register(manifest, adapter)
        return registry

    def catalog(self) -> dict[str, Any]:
        manifest = self.registry().manifest(self.CONNECTOR_ID)
        assert manifest is not None
        return {
            "ok": True,
            "connector_id": manifest.connector_id,
            "kind": manifest.kind,
            "configured": manifest.configured,
            "enabled": manifest.enabled,
            "read_only": True,
            "raw_sql": False,
            "allowed_tables": sorted(self.allowed_tables),
        }

    async def read(
        self,
        table: str,
        columns: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        order_by: str = "",
        order_direction: str = "ASC",
        limit: int = 100,
        search: bool = False,
    ) -> dict[str, Any]:
        action = ConnectorAction.SEARCH if search else ConnectorAction.READ
        request = ConnectorRequest(
            connector_id=self.CONNECTOR_ID,
            action=action,
            resource="operational_table",
            payload={
                "table": table,
                "columns": columns or [],
                "filters": filters or {},
                "order_by": order_by,
                "order_direction": order_direction,
                "limit": limit,
            },
        )
        evidence = await self.registry().execute(request)
        return {
            "ok": evidence.ok,
            "action": evidence.action.value,
            "result": evidence.result,
            "provenance": evidence.provenance,
        }


__all__ = ["SQLiteConnectorAdapter", "SQLiteConnectorProtocolService"]
