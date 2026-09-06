# DPN AI v10 Deep Research Web Worker

## Purpose

`DeepResearchWebWorker` connects the existing bounded `WebResearchRuntime` to the v10 Deep Research evidence graph. It intentionally reuses the mature search/fetch/ranking pipeline instead of creating a second network stack.

## Trust boundary

The worker accepts only `ResearchWorkstream.WEB` tasks. The existing web runtime remains responsible for bounded search/fetch behavior and upstream network safety. The worker treats runtime output as untrusted until each source has a source ID, URL, domain, bounded quality/freshness values, and admissible evidence text.

A failed runtime response, malformed source list, missing provenance, duplicate source identity, invalid evidence score, or required task with no admissible evidence fails closed.

## Atomic evidence admission

All returned sources and evidence nodes are staged and validated before graph mutation. The worker also preflights source/evidence identifiers against the live graph. A conflicting identity therefore rejects the entire worker result without partially admitting earlier sources.

## Evidence minimization

Evidence excerpts are bounded to a configurable maximum (default 8,000 characters). Raw fetch failure bodies are not copied into `WebWorkerResult`; only a partial flag and failure count are returned. Provenance retained on evidence includes task/workstream identity, domain, publication timestamp, authority score, and relevance score.

## Current readiness

This checkpoint completes the first concrete Deep Research workstream integration: Research Director -> WEB task -> existing WebResearchRuntime -> validated EvidenceGraph admission. Document and structured-data workers, claim extraction/synthesis, citation acceptance, and end-to-end multi-agent orchestration remain in Batch 7.
