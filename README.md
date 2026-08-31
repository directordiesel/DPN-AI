# DPN AI v5.0.7 — Adaptive Interface and Sentinel HD

DPN AI v5.0.7 preserves the complete v5.0.6 intelligence, streaming, document, voice, mission and tool platform while improving two areas reported after real use:

1. Control-center sections could still be cut off at browser zoom, on short laptop displays, or inside wide tables and boards.
2. The Sentinel male voice could sound slow, grainy and over-processed.

## Interface upgrade

- Every control-center modal is bounded by the actual visible browser height.
- Wide file lists, audit tables and task boards scroll inside their panel.
- Forms, toolbars and buttons wrap instead of leaving the viewport.
- Short-height and narrow-screen responsive modes are included.
- The sidebar, chat, composer and modal body remain independent scroll regions.
- Stale templates are repaired dynamically instead of causing `innerHTML` null errors.
- A cache-repair screen appears when the browser mixes incompatible interface files.

## Sentinel HD

- New primary model: `en_US-ryan-high`.
- Existing `en_GB-alan-medium` remains an automatic fallback.
- Default pace increased from 0.82x to 0.89x.
- Clear, Natural and Warm delivery tones.
- Reduced compression, filtering and automatic make-up gain.
- Lower synthesis noise and more natural pauses.
- The interface shows whether the HD or legacy model is active.

Run `install_sentinel_hd_windows.bat` once to download the improved male model. The old voice remains available if the download is skipped or fails.

## Existing installation

Apply the smaller v5.0.7 patch. It preserves `.env`, `data`, `workspace`, models, voices, conversations, projects, memories, plugins and settings.

## Clean installation

Use the complete v5.0.7 release and run `repair_windows.bat`.