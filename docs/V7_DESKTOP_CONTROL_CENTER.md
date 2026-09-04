# DPN AI v7 Desktop Control Center

This development document defines the desktop-first control-center contract for the active v7 branch. Stable `main` remains v6.0.0 until an explicitly authorized release merge.

## Goals

- Present real local runtime, model, connector, project, mission, automation, approval, security, and verification state.
- Keep failed, blocked, cancelled, and approval-waiting work visible.
- Preserve per-project scope and evidence provenance.
- Support pause, resume, retry, cancel, checkpoint restore, safe restart, and diagnostics.
- Remain compatible with the planned v8 Windows executable shell, system tray, notifications, updater, file-open/deep-link integration, and terminal-free normal startup.
- Keep stable-release branding separate from active development-channel branding.

## Desktop surfaces

Overview, Chat, Missions, Coding, Creator, Projects, Memory, Automations, Research, Connectors, Models, Approvals, Files, Runs, Security, Diagnostics, and Settings.

## Safety invariants

The UI must never fabricate online/model/connector status, never hide failed work, never auto-approve protected actions, and never report completion without backend verification evidence.

## Version consistency

The repository currently uses `VERSION` as the stable release marker. Runtime and UI version strings must be reconciled during comprehensive v7 security/QA so a future executable exposes one authoritative version source plus an explicit development-channel indicator.
