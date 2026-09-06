# DPN AI v10.0.0 — Deep Research Structured Data Worker

## Purpose

`DeepResearchDataWorker` connects the v10 Deep Research Engine's DATA workstream to the existing governed SQLite connector. It does not introduce a second database access layer and it never accepts raw SQL.

The worker requires an explicit `DataQuerySpec` containing a table, bounded columns, equality filters, ordering, and a row limit. The existing `SQLiteConnectorProtocolService` remains responsible for the live table allowlist, identifier validation, value parameterization, `mode=ro` database access, and `PRAGMA query_only=ON` enforcement.

## Security boundary

The worker is intentionally narrower than the underlying connector:

- no raw SQL is accepted or generated from model text;
- execution is forced through the connector's `read` action with `search=False`;
- the worker caps a research query at 100 rows even though the lower connector has its own larger hard ceiling;
- returned evidence must identify the requested table and the SQLite provider;
- provenance must explicitly prove `read_only=true` and `parameterized=true`;
- returned row counts must exactly match the returned rows and may not exceed the requested limit;
- a required DATA task fails closed when no admissible evidence exists;
- malformed rows, wrong-table results, provider changes, non-read actions, provenance weakening, and graph collisions are rejected before graph mutation.

The worker cannot write, update, delete, migrate, or run arbitrary statements. Approval does not convert this adapter into a write path.

## Evidence model

One `ResearchSource` represents the governed table/database/connector identity. Each returned row becomes a separate `EvidenceNode` with:

- deterministic evidence identity;
- SQLite database and table provenance;
- a bounded canonical JSON excerpt;
- DATA workstream metadata;
- explicit read-only and parameterized execution markers.

Rows are staged and validated before any source/evidence is committed to the Evidence Graph. Existing source and evidence identities are preflighted so a collision cannot leave a partial batch.

## Integration path

`ResearchDirector -> DATA ResearchTask -> DataQuerySpec -> DeepResearchDataWorker -> SQLiteConnectorProtocolService -> read-only SQLite adapter -> provenance validation -> EvidenceGraph`

This complements the existing v10 WEB and DOCUMENTS paths without duplicating their runtimes.

## Regression coverage

`tests/test_deep_research_data_worker_v10.py` covers:

- governed row admission and connector call shape;
- wrong-workstream rejection before runtime execution;
- non-read action rejection;
- read-only/parameterized provenance enforcement;
- table/provider escape rejection;
- row-limit and declared-count enforcement;
- required versus optional empty results;
- query-spec bounds and duplicate-filter rejection;
- excerpt bounding; and
- graph-collision preflight without partial evidence mutation.

## Remaining Batch 7 work

The DATA worker completes the first concrete worker for each planned research workstream. Batch 7 still requires mixed-workstream claim extraction, fact-check/conflict orchestration, citation acceptance, evidence-grounded synthesis, and final end-to-end readiness evidence before release consideration.
