# DPN AI Local Voice System — v5.0.7

DPN AI supports local microphone transcription, hands-free conversation and local read-aloud speech.

## DPN Sentinel HD

Sentinel is an original male operations voice. Version 5.0.7 prefers the higher-quality `en_US-ryan-high` Piper model and uses the earlier `en_GB-alan-medium` model automatically until the HD model is installed.

Natural preset:

- Pace: 0.89x
- Shorter, more conversational pauses
- Lower synthesis noise
- Minimal de-harsh filtering
- Gentle peak control without aggressive make-up gain
- Clear, Natural and Warm tone choices

Run:

```text
install_sentinel_hd_windows.bat
```

The interface reports the active model and displays **Upgrade to HD** when the legacy model is being used.

## DPN Aurora

Aurora remains an original soft female narrator and conversational companion.

Natural preset:

- Pace: 0.78x
- Longer sentence and paragraph pauses
- Softer high-frequency response
- Lower peak target
- Gentle and Natural delivery choices

## Narration pipeline

Piper output is generated in readable phrases rather than one uninterrupted response. DPN AI then applies profile-specific processing:

1. Sentence-aware phrase splitting
2. Explicit paragraph breathing room
3. Safe splitting of unusually long clauses
4. Tone-specific high-frequency control
5. Smooth peak compression
6. Conservative gain adjustment
7. Click-safe phrase fades

The processing is local and does not upload speech text or audio.