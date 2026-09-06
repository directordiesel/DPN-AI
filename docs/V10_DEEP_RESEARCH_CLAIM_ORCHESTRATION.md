# DPN AI v10.0.0 — Deep Research Claim Orchestration

## Purpose

`app/deep_research_claim_orchestrator_v10.py` connects admitted WEB, DOCUMENTS, and DATA evidence to the existing deterministic fact checker, conflict detector, citation validator, and synthesis readiness gate.

This layer does not grant a language model authority to create provenance. An injected claim extractor may propose claim text and relationships, but every referenced evidence ID must already exist in the trusted `EvidenceGraph` before a claim can be admitted.

## Trust boundary

The orchestrator sends the extractor a bounded evidence payload containing only admitted evidence identity, source identity/type, locator, excerpt, quality/freshness scores, and workstream provenance. Extractor output is treated as untrusted.

Before graph mutation the orchestrator validates:

- the research objective and evidence inventory are non-empty;
- extractor output is a bounded sequence and does not exceed the configured claim limit;
- each claim has a stable ID, bounded text, finite confidence, and at least one evidence relationship;
- support/refute references are lists without duplicates or overlap;
- every referenced evidence ID already exists in the graph;
- claim IDs are unique within the proposed batch;
- claim IDs do not collide with different live-graph claims;
- when mixed-workstream mode is required, admitted relationships span at least two evidence workstreams.

All candidates are staged and preflighted before any claim is committed, preserving all-or-nothing graph admission for the extractor batch.

## Deterministic downstream verification

After admission the orchestrator runs the existing `ResearchFactChecker` across the graph, executes `ResearchConflictDetector`, builds deterministic citation references from supporting relationships, validates them with `CitationValidator`, and evaluates `DeepResearchReadinessGate`.

A claim with both qualified supporting and refuting evidence remains `disputed`. Unsupported or stale claims remain blocked. Citation-validation failure explicitly forces synthesis readiness to false.

## Security properties

The orchestrator performs no web requests, file reads, SQL queries, connector writes, shell execution, or destructive actions. Those operations remain inside their existing governed worker/runtime boundaries.

The claim extractor cannot introduce a URL, database row, document, source, or citation that was not already represented by admitted evidence. This prevents model-generated provenance from silently entering final research output.

## Verification coverage

`tests/test_deep_research_claim_orchestrator_v10.py` covers mixed WEB+DATA claim admission, fact-check and citation acceptance, unknown-evidence rollback, live claim-ID collision rollback, mixed-workstream enforcement, disputed claims, duplicate/unattached evidence rejection, extractor return-type bounds, and claim-count bounds.

## Remaining Batch 7 work

The next integration step is evidence-grounded research writing. The writer must consume only verified claims and accepted citations, preserve unresolved conflicts instead of smoothing them away, and produce an end-to-end research result whose release/readiness evidence can be tested across WEB, DOCUMENTS, and DATA workers.
