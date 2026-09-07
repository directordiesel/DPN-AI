# DPN AI v10.0.0 — Long-Horizon Mission Memory Bridge

## Purpose

Batch 8 now connects the completed Batch 5 long-horizon mission runtime to the Advanced Layered Memory architecture.

`app/long_horizon_memory_bridge_v10.py` promotes only integrity-verified, successfully completed long-horizon missions into **episodic memory**. The bridge is intentionally conservative: it does not reinterpret arbitrary mission output as semantic truth.

## Trust boundary

Before any durable memory write, the bridge re-reads persisted mission/checkpoint/step state and requires all of the following:

- the mission exists and is persisted as `completed`;
- the latest v10 long-horizon checkpoint passes the checkpoint SHA-256 integrity codec;
- the latest verified checkpoint lifecycle is `completed`;
- there is no next-step cursor, failed-step state, or pending approval state;
- the exact set of completed step IDs in the checkpoint matches the exact persisted completed-step set;
- the deterministic mission review verdict is `pass`;
- the security review exists and is not `fail`;
- evidence IDs, artifact references, and step counts remain inside bounded limits.

Any disagreement fails closed before memory mutation.

## What is stored

A successful mission is written as `MemoryLayer.EPISODIC` / `KnowledgeClass.EPISODE` with typed provenance:

- source type: `long_horizon_mission`;
- source ID: the integrity-verified checkpoint ID;
- evidence IDs: the verified checkpoint evidence IDs;
- confidence: `1.0`;
- authority: `0.9`.

The episodic payload contains only bounded operational evidence: mission identity/objective, checkpoint identity/revision, completed step IDs/titles/status, evidence IDs, artifact references, and budget usage.

Raw tool arguments, approval payloads, credentials, arbitrary provider transcripts, and full step result dictionaries are not copied into memory.

## Semantic memory policy

This checkpoint deliberately does **not** promote mission prose or step output directly into semantic fact memory. Long-horizon mission completion proves that a mission passed its execution/review contract; it does not prove that every arbitrary generated sentence is globally true.

Semantic promotion remains restricted to evidence-backed fact flows such as the Batch 8 Deep Research memory bridge until controlled promotion/supersession policy is implemented.

## Sensitive memory

The bridge accepts `sensitive=True` only as a classification signal and forwards it to `AdvancedLayeredMemory`.

It has no `approval_granted` argument and cannot self-authorize a sensitive write. The existing externally injected memory approval guard remains authoritative.

## Failure semantics

Memory persistence failures are returned explicitly. The bridge never claims a successful promotion if `AdvancedLayeredMemory.remember()` fails.

## Regression coverage

`tests/test_long_horizon_memory_bridge_v10.py` covers:

- verified terminal mission promotion;
- non-completed mission rejection;
- checkpoint integrity tampering;
- persisted-step/checkpoint disagreement;
- failed security review rejection;
- unresolved approval-state rejection;
- sensitive classification propagation without an approval bypass;
- explicit memory-storage failure reporting.

## Next Batch 8 work

The next memory checkpoints remain controlled promotion/supersession, deduplication/compaction/recovery, governed memory tools/APIs, and dedicated memory quality/readiness benchmarks.
