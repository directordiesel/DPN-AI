# DPN AI v8.0.0 Release Candidate

> Status: implementation complete on the v8 desktop branch; not yet published as a stable release.

## Windows desktop platform

- Added a native Windows desktop launcher and supervisor with bounded restart behavior and safe-mode support.
- Added the black/purple DPN AI Desktop Control Center with live runtime status surfaces and no simulated production metrics.
- Added versioned desktop API and SSE status streaming while preserving one unified AI/runtime/project/memory/agent architecture.
- Added Windows executable packaging and installer foundations with integrity manifests and trusted-runner isolation.
- Added Windows startup, context-menu/Open-with, tray, and notification integration using per-user scope.

## Reliability and recovery

- Added persistent crash journaling and automatic safe-mode escalation after repeated crashes.
- Added repository-bounded recovery backups with SHA-256 sidecars and retention controls.
- Added bounded diagnostics that exclude environment secrets and private runtime credentials.
- Preserved the validated snapshot/restore subsystem as the sole restore authority.

## Performance and model lifecycle

- Added real CPU/RAM telemetry and configurable pressure thresholds.
- Added fail-closed admission controls for heavy work under resource pressure.
- Added explicit model load, ready, use, failure, idle eviction, and critical-pressure eviction states.
- Preserved provider-specific model loading in the existing model gateway/Ollama runtime.

## Security, QA, and release gates

- Added dedicated v8 desktop validation on the trusted DIESEL-118 self-hosted Windows runner.
- Added full v8 regression coverage for desktop platform, supervisor, service API, updater, Windows installer/integration/packaging, recovery, and resource controls.
- Added a strict non-publishing v8 release-readiness gate for version metadata, required files, documentation, packaging isolation, release policy, and signing readiness.
- Kept pull-request Windows binary packaging intentionally skipped.
- Kept production signing as an explicit blocker until a real trusted signing provider/certificate is integrated; unsigned development artifacts are not misrepresented as signed production releases.

## Current release-candidate blockers

- Stable version promotion from 6.0.0 to 8.0.0 must be performed as one coordinated change across VERSION, runtime metadata, UI version markers, and related release metadata.
- Production Windows signing must be integrated and verified before stable publication.
- PR #29 must remain draft until exact-head release gates are green and an explicit stable merge/release is authorized.

---

# DPN AI v5.0.7 Changelog

## Adaptive interface

- Added dynamic viewport-height tracking through `visualViewport`.
- Increased modal width and usable height while retaining viewport boundaries.
- Added independent horizontal scrolling for wide tables, boards and audit rows.
- Added auto-fit responsive grids for diagnostics, projects, voice profiles and metrics.
- Added compact layouts for short laptop displays and high browser zoom.
- Added wrapping for modal actions, forms, toolbars, headers and controls.
- Added stale message-template repair and null-safe streaming updates.
- Added an in-app service-worker/cache repair screen.
- Advanced the interface cache to v5.0.7.

## Sentinel male voice

- Changed Sentinel's preferred Piper model to `en_US-ryan-high`.
- Retained `en_GB-alan-medium` as an automatic fallback.
- Increased natural pace to 0.89x.
- Added Clear, Natural and Warm tone presets.
- Reduced noise scale, compression and make-up gain.
- Reduced sentence and paragraph pauses.
- Added an HD-upgrade button and a standalone Windows voice installer.
- Migrated the old 0.82x browser default automatically.

## Aurora

- Retained the soft female profile.
- Added Gentle and Natural tone choices.
- Slightly increased the natural pace to 0.78x while keeping longer gentle pauses.