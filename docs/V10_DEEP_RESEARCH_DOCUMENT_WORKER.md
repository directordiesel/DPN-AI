# DPN AI v10.0.0 — Deep Research Document Worker

## Purpose

`DeepResearchDocumentWorker` is the Batch 7 bridge between the existing scoped `RAGEngine` and the v10 Evidence Graph. It adds document/project evidence to deep research without creating a second file-search, semantic-search, or filesystem-access implementation.

## Trust boundary

The worker does **not** open paths, enumerate directories, or parse files itself. All retrieval is delegated to the existing RAG runtime, which already combines semantic memory and workspace keyword search, performs deterministic deduplication/reranking, and bounds source/context size.

The worker independently verifies the returned namespace before graph admission. Supported scopes are:

- `global`
- `project:<project_id>`
- `kb:<knowledge_base>`
- `project:<project_id>:kb:<knowledge_base>`

A runtime-level namespace mismatch or an individual source whose namespace differs from the requested scope fails closed before graph mutation.

## Evidence admission

Each admitted source must contain:

- stable `source_id`
- source type
- exact retrieval namespace
- non-empty locator
- non-empty content
- bounded retrieval/relevance score

The worker converts each admitted result into a `ResearchSource` and `EvidenceNode`, preserving the local locator and requested namespace. Local evidence uses a non-network `dpn://retrieval/...` identity and is marked `local_retrieval=true`; it does not claim an external web origin.

Excerpts are bounded independently from the upstream RAG context. The worker accepts at most 50 sources by construction and defaults to 12 sources / 8,000 characters per excerpt.

## Transactional graph behavior

The complete retrieval result is staged first. Duplicate source IDs, malformed provenance, namespace escape, or collision with already-admitted graph evidence is detected before commit. The batch is therefore all-or-nothing: a later malformed document cannot leave earlier sources partially admitted.

Required document tasks fail if they produce no admissible evidence. Optional document tasks may legitimately produce zero evidence.

## Security properties

- no raw filesystem access is introduced;
- no document write/generation authority is granted;
- project/knowledge-base scope is revalidated at the worker boundary;
- caller input is not converted into paths or SQL;
- local retrieval is explicitly distinguished from web provenance;
- graph admission remains provenance-first and fail-closed.

## Verification coverage

`tests/test_deep_research_document_worker_v10.py` covers:

- scoped RAG-to-EvidenceGraph admission;
- combined project + knowledge-base scope;
- runtime namespace escape rejection;
- per-source namespace escape rollback;
- duplicate source rejection;
- malformed provenance rollback;
- required vs optional empty results;
- wrong-workstream rejection before retrieval;
- source-count and excerpt-size bounds.

## Remaining Batch 7 work

The document worker completes the second concrete Research Director workstream. Batch 7 still requires the structured-data worker, evidence-grounded claim extraction/research writing, citation acceptance, conflict/fact-check integration across mixed workstreams, and final end-to-end readiness evidence.
