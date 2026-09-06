# DPN AI v10.0.0 — Governed SQLite Connector

Batch 6 now includes a local SQL connector implemented over the existing DPN AI SQLite database.

## Security model

The connector is read-only by construction. It does not accept raw SQL and does not expose a generic SQL execution surface. Callers select only an explicitly allow-listed operational table, a bounded list of columns, equality filters, optional ordering, and a row limit.

Execution opens SQLite with `mode=ro`, enables `PRAGMA query_only=ON`, validates identifiers against a conservative identifier grammar and the live table schema, parameterizes every caller-supplied value, and clamps row output to at most 500 rows.

The default table allowlist is limited to:

- `projects`
- `project_tasks`
- `operation_runs`
- `audit_events`
- `automations`

Conversation messages, memory content, knowledge chunks, secret storage, and arbitrary database tables are not part of the connector allowlist.

## Protocol integration

The connector is represented as `sqlite:dpn-core` in the unified DPN Connector Protocol ecosystem with local `read` and `search` capabilities on `operational_table`. It is included in unified ecosystem catalog and health output.

The plugin exposes two governed tools:

- `dpn_connector_sql_catalog` — reports the fixed SQL connector policy and allowlist.
- `dpn_connector_sql_read` — performs bounded parameterized reads only.

Both are connector-gated and classified as read-only. There is intentionally no SQL write tool in Batch 6.

## Fail-closed behavior

The connector refuses execution when the database file is unavailable, the table is not allow-listed, an identifier is malformed, a requested/filter/order column does not exist in the live schema, the filter object is too large, or a non-read/search protocol action is attempted.

Direct adapter calls cannot bypass the read-only boundary: create/update/delete requests are rejected even if an approval flag is present.

## Verification coverage

`tests/test_dpn_sql_connector_v10.py` covers allowlist enforcement, parameterized filtering, bounded limits, identifier-injection rejection, unknown-column rejection, direct write-action rejection, and fail-closed health when the database is missing.

`tests/test_dpn_connector_approval_bridge_v10.py` pins the SQL catalog/read tools to the connector gate and read risk classification so later changes cannot silently turn this local SQL surface into an unreviewed mutation path.
