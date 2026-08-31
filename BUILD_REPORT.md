# DPN AI v5.0.7 Validation Report

## Scope

This release upgrades the v5.0.6 platform with adaptive interface containment, stale-template recovery and a cleaner/faster Sentinel male voice path.

## Automated validation

- Complete Python test suite passed: **77 tests**.
- Python compilation passed.
- JavaScript syntax validation passed.
- Live FastAPI startup passed.
- `/api/health` returned version 5.0.7.
- 76 built-in tools loaded.
- 13 skill packs loaded.
- 6 workflows loaded.
- Static HTML served v5.0.7 cache-busted assets.

## Added regression coverage

- Viewport-bounded control-center modals.
- Wide table, board and audit scrolling.
- Auto-fit responsive section grids.
- Short-display compact mode.
- Browser cache recovery.
- Stale message-template repair.
- Sentinel HD primary-model selection.
- Legacy Sentinel fallback.
- Faster natural male pace.
- Reduced compression and make-up gain.
- Selectable voice-tone transmission.

## Environment limitation

The build environment did not download the `en_US-ryan-high` model. The download path, active-model selection and legacy fallback were validated in code. The target computer downloads the model through Piper when `install_sentinel_hd_windows.bat` or **Upgrade to HD** is used.