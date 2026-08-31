# DPN AI v5.0.4 UI Layout Fix

This hotfix corrects control and chat areas being cut off in laptop-height windows, browser zoom, and smaller displays.

## Fixed

- The entire left sidebar now has its own visible vertical scrollbar.
- The operation list remains separately scrollable without hiding the Control Center buttons.
- The main chat output is constrained to the browser viewport and always has a visible scrollbar.
- The voice/composer area can scroll internally when attachments or a long prompt make it tall.
- Long code, command output, traces, links, tables, images, and file chips remain inside the chat width.
- Smaller-height screens receive a compact layout automatically.
- Top controls can scroll horizontally instead of being clipped.
- The web-app cache key and asset URLs were changed so the old broken CSS is not reused.

## Apply over an existing installation

The easiest path is to use the separate UI patch ZIP and run `apply_ui_hotfix_windows.bat`.

After applying it:

1. Close the old DPN AI browser tab.
2. Stop and restart `run_dpn_ai.bat`.
3. Open DPN AI again.
4. Press `Ctrl+F5` once if the old layout remains visible.