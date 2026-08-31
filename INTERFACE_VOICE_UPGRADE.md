# DPN AI v5.0.7 Interface and Sentinel Voice Upgrade

## Interface

- Every control-center modal is bounded by the visible browser viewport.
- Wide sections scroll horizontally inside their own panel instead of being cut off.
- Forms, cards, toolbars and buttons wrap on narrow displays and browser zoom.
- Short laptop-height screens use a compact mode.
- Missing/stale interface elements trigger an in-app cache repair screen instead of a JavaScript null crash.

## Sentinel voice

- Primary model changed to the higher-quality `en_US-ryan-high` Piper voice.
- Existing `en_GB-alan-medium` remains an automatic fallback until the HD model is installed.
- Natural pace is now 0.89x instead of 0.82x.
- Reduced noise, compression and make-up gain prevent grain and volume pumping.
- Clear, Natural and Warm delivery tones are selectable.
- Aurora retains Gentle and Natural delivery modes.

Run `install_sentinel_hd_windows.bat` once after applying the patch to download the improved male voice.