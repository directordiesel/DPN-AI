# DPN AI v8 Desktop Platform

DPN AI v8 turns the validated v7 Agentic Intelligence runtime into a production Windows desktop platform while preserving one unified AI, project, memory, agent, creator, automation, connector, research, vision, and verification architecture.

## Architecture

The Windows application is the primary DPN AI runtime and local intelligence hub. Android and future clients connect to the same scoped service layer rather than implementing separate AI stacks.

### Desktop layers

1. **Native launcher / supervisor**
   - Starts the local DPN AI service without a normal console window.
   - Performs preflight checks, single-instance enforcement, health monitoring, graceful shutdown, crash recovery, and diagnostic collection.
   - Never silently weakens authentication or security controls to recover a failed launch.

2. **Local AI service/API**
   - Reuses the existing DPN AI application and v7 intelligence modules.
   - Exposes versioned loopback-first HTTP/WebSocket interfaces for the desktop shell and later paired mobile clients.
   - Keeps project, memory, tool, connector, approval, and audit policy centralized.

3. **Desktop shell / Control Center**
   - DPN black/purple desktop-first interface.
   - Command Center navigation, chat, projects, missions, coding, creator/document/image studios, research, automations, connectors, models, memory, security, devices, diagnostics, and settings.
   - Supports persistent window/layout state and future native system integration.

4. **Windows integration**
   - System tray and notifications.
   - Optional launch-at-sign-in.
   - File/context-menu and Open with DPN AI integration only through explicit installation/user configuration.
   - Clipboard, screenshot, voice, and global command surfaces remain permission-aware.

5. **Packaging / update / recovery**
   - Reproducible Windows executable build.
   - Installer with install, repair, update, and uninstall paths.
   - Signed release/update metadata, staged updates, integrity checks, rollback, backup-before-migration, and safe mode.

## Security invariants

- Local-first and loopback-first by default.
- No silent cloud transfer or remote exposure.
- No database exposed directly to desktop/mobile clients.
- Secrets remain outside distributable source/configuration artifacts.
- External writes and destructive actions continue to use v7 approval boundaries.
- Remote access is disabled until an authenticated, encrypted, scoped gateway is explicitly configured.
- Updates must be integrity-verified before activation.
- Recovery cannot bypass authentication, authorization, audit, or verification gates.

## v8 implementation order

1. Desktop platform foundation and contracts.
2. Native launcher/supervisor and local service lifecycle.
3. Desktop Control Center shell and navigation.
4. Local versioned API + streaming/event channel.
5. Windows executable packaging.
6. Installer/repair/uninstall.
7. Updater and rollback.
8. Windows tray/notifications/context integration.
9. Crash recovery, safe mode, backups, diagnostics.
10. Performance/resource controls and model lifecycle integration.
11. Security/QA/package validation.
12. v8 desktop release gates.

## Release policy

Development occurs on `feature/dpn-ai-desktop-v8`. Stable `main` remains the validated release line until the v8 release candidate passes its required CI, security, runtime/recovery, packaging, installer, and Windows validation gates and Diesel explicitly authorizes the stable merge.
