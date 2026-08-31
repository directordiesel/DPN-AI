# DPN AI v5.0.6 Voice Narration Fix

This release changes the voice system from raw one-block speech synthesis into a narration-oriented pipeline.

## DPN Sentinel

- Natural pace: 0.82×
- Measured, composed operations delivery
- Firmer technical diction
- Moderate sentence pauses
- Warmer but still authoritative output level

## DPN Aurora

- Natural pace: 0.76×
- Longer pauses between thoughts
- Lower variation and softer consonant energy
- Stronger de-harsh smoothing
- Gentler compression and quieter peak target
- Intended for comfortable conversation and long-form reading

## Audio processing

Piper speech is generated in bounded phrases. DPN AI then applies:

1. Sentence and paragraph breathing room
2. High-frequency de-harsh smoothing
3. Gentle peak compression
4. Conservative output normalization
5. Short fades to prevent clicks between generated phrases

No online voice service is required. Existing Sentinel and Aurora model files remain compatible and do not need to be downloaded again.