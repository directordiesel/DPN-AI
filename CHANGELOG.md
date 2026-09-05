# DPN AI Changelog

## v9.0.0 — Stable

DPN AI v9.0.0 is the current published stable release. It consolidates the v9 development program into one local-first, permission-aware, evidence-driven AI operations platform.

### Intelligence Core + Agent Runtime
- Added deterministic planner/executor/reviewer orchestration.
- Added task dependency enforcement and mission-state tracking.
- Added bounded retries, evidence requirements, failure blocking, and completion summaries.
- Added reusable agent-context seams without forcing unsafe rewrites of large runtime files.

### Coding Agent + GitHub Engineering
- Added repository-aware coding-agent foundations.
- Added change-risk analysis and high-severity diff escalation.
- Added repository-engineering planning and CI-diagnostics support.
- Added self-review/test-selection foundations for safer multi-file changes.

### Tools + Permission/Sandbox Architecture
- Added shared permission and risk-policy foundations.
- Added approval-aware execution and tool-risk classification.
- Added host-fallback approval hardening for sandbox execution.
- Added fail-closed behavior for unsupported or disallowed tool paths.

### Memory + RAG + Knowledge Bases
- Added scoped memory and semantic retrieval foundations.
- Added RAG engine, context assembly, and knowledge-base support.
- Added project-aware memory isolation and persistent agent-context runtime seams.

### Research + Web Intelligence
- Added structured research intelligence runtime.
- Added source-oriented web research tools.
- Added claim-conflict detection foundations.
- Added plugin registration and compatibility handling for research capabilities.

### Artifact Studio
- Expanded DOCX, PDF, XLSX, and PPTX generation architecture.
- Added artifact orchestration and validation metadata.
- Added artifact integrity checks and spreadsheet-enrichment support.
- Preserved native-format generation through the existing document factory architecture.

### Image Generation + Vision/Edit Architecture
- Added provider capability discovery for generation, editing, and vision.
- Added workspace-safe image request planning and operation validation.
- Added real ComfyUI-backed image generation.
- Added fail-closed editing and vision routes when a compatible provider is not configured.

### Scheduler + Autonomous Workflows
- Added one-time, recurring, and condition-oriented automation definitions.
- Added overlap policies, step dependencies, bounded retry/backoff, and completion summaries.
- Added workflow approval/evidence metadata.
- Preserved fail-closed behavior for condition execution when a condition provider is absent.

### Voice + Multimodal Interaction
- Added voice-session state and multimodal attachment handling.
- Added barge-in/interruption state and hands-free session foundations.
- Preserved the existing local STT/TTS stack with Piper, faster-whisper, and fallback voices.

### Desktop UX
- Added the v9 black/purple desktop experience.
- Added command palette, keyboard shortcuts, live activity surfaces, and status-count mirroring.
- Added Task/Approval/Agent routing improvements and responsive/accessibility behavior.
- Preserved evidence-first wording for pause/resume/cancel operations.

### Android v2 + Secure Pairing
- Added stronger device-trust policy and revoked/unpaired fail-closed behavior.
- Added Android Keystore-backed session handling.
- Added shorter remote sessions and authenticated gateway requirements.
- Added user-presence requirements for remote writes and explicit approval for destructive actions.

### Models + Local AI Routing
- Added deterministic local-first routing and capability matching.
- Added health-aware bounded fallback.
- Preserved external-endpoint denial unless explicitly allowed.
- Added malformed-policy fail-closed behavior.

### Security, Vault, and Audit Hardening
- Added prompt-injection assessment and plaintext-secret rejection.
- Added secret-reference handling and URL/network authorization policy.
- Added tamper-evident chained audit envelopes with SHA-256/HMAC verification foundations.
- Preserved exact deferred approval arguments in the encrypted vault while persisting only redacted previews.

### Performance + Recovery + Updating
- Expanded performance/resource management and recovery readiness.
- Improved snapshot, integrity, rollback, health, diagnostics, updater, and migration evidence foundations.

### SDK + Integrations
- Added governed SDK/integration request contracts.
- Added operation classification and idempotency/write-verification expectations.
- Preserved connector/MCP approval, allowlist, and secret boundaries.

### Evaluations + Regression/Security Testing
- Added weighted production-readiness evaluation.
- Added critical-case fail-closed behavior.
- Added adversarial coverage for secret leakage, prompt injection, network policy, SDK idempotency, and missing release evidence.

### Installer + Release Engineering
- Added release-candidate validation contracts and exact Git SHA requirements.
- Added version/channel coherence checks.
- Added required SBOM/checksum/release-manifest evidence.
- Added installer/package, rollback/recovery, CI, Security, Runtime/Recovery, and evaluation readiness requirements.

### Stable Release Publication
- Promoted all coordinated version sources to **9.0.0**.
- Passed exact-head CI, DPN Security Gate v2, and Runtime & Recovery Assurance before stable merge.
- Published `v9.0.0` from the exact stable `main` commit.
- Generated and attached:
  - `DPN-AI-v9.0.0-source.zip`
  - `SHA256SUMS.txt`
  - `SOURCE_SHA256SUMS.txt`
  - `SBOM.spdx.json`
  - `RELEASE_MANIFEST.txt`
  - `DEPENDENCY_INVENTORY.txt`

## v8 Desktop Platform — Historical Foundation

The v8 desktop work established the native Windows desktop launcher/supervisor, black/purple Control Center, versioned desktop API, Windows packaging and installer foundations, updater/rollback contracts, per-user integration, crash journaling, integrity-tagged recovery, diagnostics hardening, CPU/RAM pressure controls, and model lifecycle management that v9 builds upon.

## v5.0.7 — Historical Foundation

### Adaptive interface
- Added dynamic viewport-height tracking through `visualViewport`.
- Increased modal width and usable height while retaining viewport boundaries.
- Added independent horizontal scrolling for wide tables, boards and audit rows.
- Added auto-fit responsive grids for diagnostics, projects, voice profiles and metrics.
- Added compact layouts for short laptop displays and high browser zoom.
- Added wrapping for modal actions, forms, toolbars, headers and controls.
- Added stale message-template repair and null-safe streaming updates.
- Added an in-app service-worker/cache repair screen.

### Sentinel male voice
- Changed Sentinel's preferred Piper model to `en_US-ryan-high`.
- Retained `en_GB-alan-medium` as an automatic fallback.
- Added Clear, Natural and Warm tone presets.
- Improved pace and speech-processing defaults.
- Added HD voice upgrade/install paths.

### Aurora
- Retained the soft female profile.
- Added Gentle and Natural tone choices.
- Improved natural pacing while preserving the gentler preset.

---

For the active engineering direction after v9.0.0, see [`ROADMAP.md`](ROADMAP.md).
