# DPN AI v9 Capability Matrix

This matrix documents capability state for the stable v9 architecture. It is intentionally conservative: architecture alone does not make a capability live.

## State Definitions

| State | Meaning |
| --- | --- |
| **Available** | Core implementation exists and can operate when its normal local prerequisites are present. |
| **Configurable** | Architecture and safety boundaries exist, but an optional provider/service must be configured. |
| **Degraded** | Capability exists but is operating with fallback behavior or missing a preferred dependency. |
| **Unavailable** | Required provider/runtime is absent; execution should fail closed instead of simulating success. |

## Intelligence and Agents

| Capability | State | Notes |
| --- | --- | --- |
| Planner / executor / reviewer runtime | Available | Deterministic orchestration, dependencies, retries, evidence and failure blocking. |
| Mission state tracking | Available | Persistent progress and terminal-state foundations. |
| Specialist-agent routing | Available | Coding, research, security, automation, artifact/general roles through shared orchestration patterns. |
| Hidden-chain-of-thought exposure | Unavailable | Operational summaries/evidence should be surfaced instead of private internal reasoning. |

## Coding and Repository Engineering

| Capability | State | Notes |
| --- | --- | --- |
| Repository-aware coding-agent foundation | Available | Supports structured engineering and validation workflows. |
| Diff risk classification | Available | High-severity findings can force high-risk classification. |
| CI diagnostics | Available | GitHub workflow failure diagnosis foundations are implemented. |
| Fully autonomous destructive repo administration | Unavailable | High-risk/destructive actions remain approval/policy constrained. |

## Memory, RAG, and Knowledge

| Capability | State | Notes |
| --- | --- | --- |
| Persistent memory services | Available | Includes scoped/project-aware foundations. |
| Semantic retrieval | Available | Semantic search/index architecture present. |
| RAG context assembly | Available | Source-aware retrieval/context assembly foundations. |
| Advanced v9.1 reranking/quality expansion | Configurable / in development | Planned hardening and quality work builds on stable v9. |

## Research and Web Intelligence

| Capability | State | Notes |
| --- | --- | --- |
| Structured research runtime | Available | Research tooling and plugin registration are present. |
| Claim-conflict detection | Available | Conflict-detection foundations exist. |
| External web access | Configurable | Depends on configured runtime/network permissions. |
| Unrestricted browsing | Unavailable | Network and permission boundaries remain intentional. |

## Documents and Data

| Capability | State | Notes |
| --- | --- | --- |
| DOCX generation | Available | Built-in document tooling. |
| PDF generation | Available | Built-in artifact generation path. |
| XLSX generation | Available | Spreadsheet tooling and enrichment support. |
| PPTX generation | Available | Presentation generation support. |
| Artifact validation metadata | Available | Integrity/validation information accompanies Artifact Studio workflows. |

## Images and Vision

| Capability | State | Notes |
| --- | --- | --- |
| ComfyUI image generation | Configurable | Real provider implementation; requires a compatible ComfyUI endpoint/workflow. |
| Image editing | Configurable | Routing, validation and provider interfaces exist; requires a configured edit provider. |
| Vision/image analysis | Configurable | Routing, validation and provider interfaces exist; requires a configured vision provider. |
| Simulated editing/vision without provider | Unavailable | v9 intentionally fails closed. |

## Voice and Multimodal

| Capability | State | Notes |
| --- | --- | --- |
| Piper TTS | Configurable | Available when Piper/model assets are installed. |
| faster-whisper STT | Configurable | Available when dependency/model assets are installed. |
| System voice fallback | Degraded | Fallback path when preferred neural voice stack is unavailable. |
| Voice session state / barge-in foundations | Available | Session and interruption control architecture present. |
| Android background unrestricted microphone capture | Unavailable | Foreground/session security constraints are preserved. |

## Automation

| Capability | State | Notes |
| --- | --- | --- |
| One-time automation | Available | Supported by persisted automation runtime. |
| Recurring automation | Available | Supported by persisted automation runtime. |
| Workflow dependencies | Available | Step dependency handling implemented. |
| Retry / backoff policies | Available | Bounded retries and capped exponential backoff. |
| Condition-watch execution | Configurable | Requires a condition provider; fails closed otherwise. |

## Desktop

| Capability | State | Notes |
| --- | --- | --- |
| v9 Control Center | Available | Black/purple desktop UI. |
| Command palette | Available | Keyboard-driven command surface. |
| Task/Approval/Agent routing | Available | UI routing and activity surfaces. |
| Native Windows production signing | Configurable | Requires authorized signing certificate/provider. |

## Android v2

| Capability | State | Notes |
| --- | --- | --- |
| Secure pairing foundations | Available | Device trust lifecycle and pairing state. |
| Android Keystore-backed sessions | Available | Credential/session protection foundations. |
| Revocation / re-pair enforcement | Available | Revoked devices fail closed. |
| Remote write actions | Configurable | Require authenticated gateway plus user presence. |
| Destructive remote actions | Configurable | Require explicit approval. |
| Arbitrary unrestricted remote computer control | Unavailable | Not claimed by stable v9. |

## Models

| Capability | State | Notes |
| --- | --- | --- |
| Ollama local models | Configurable | Default local provider path. |
| OpenAI-compatible local endpoint | Configurable | Supported when explicitly configured. |
| Approved remote OpenAI-compatible endpoint | Configurable | External access must be explicitly allowed. |
| Capability-aware routing | Available | Deterministic routing foundations. |
| Health-aware fallback | Available | Bounded failover without policy bypass. |
| Automatic external fallback without permission | Unavailable | Local-first/private-first policy is preserved. |

## Security

| Capability | State | Notes |
| --- | --- | --- |
| Encrypted local secrets vault | Available | Secrets should be referenced rather than persisted in plaintext. |
| Approval revalidation | Available | Deferred actions are rechecked before execution. |
| Prompt-injection assessment | Available | Security hardening foundations included. |
| Network authorization / allowlists | Available | Private/external distinctions and endpoint policy foundations. |
| Tamper-evident audit chaining | Available | SHA-256/HMAC-based chain verification foundations. |
| Plaintext secret persistence as normal behavior | Unavailable | Rejected by design. |

## Recovery and Release

| Capability | State | Notes |
| --- | --- | --- |
| Snapshot/recovery foundations | Available | Integrity and rollback evidence paths exist. |
| Runtime & Recovery Assurance | Available | Dedicated validation workflow. |
| Production-readiness evaluation | Available | Critical missing/failing evidence fails closed. |
| SBOM generation | Available | Stable release pipeline generates SPDX SBOM. |
| Source checksums/manifests | Available | Stable release pipeline generates SHA-256 evidence. |
| Stable v9.0.0 release | Available | Published from exact validated stable commit. |

## Why This Matrix Exists

DPN AI separates **implemented architecture** from **configured provider capability**. This prevents documentation and UI from claiming that a feature works when a dependency, credential, model, service, provider, or approval is missing.

The v9.1 roadmap will continue moving capabilities from Configurable/Degraded toward Available where that can be done safely and truthfully.
