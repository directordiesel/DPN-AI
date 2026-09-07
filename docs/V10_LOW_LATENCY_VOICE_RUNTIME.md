# DPN AI v10.0.0 — Advanced Low-Latency Voice Runtime

## Purpose

Batch 10 extends the existing DPN AI voice stack instead of replacing it. The existing `VoiceAdapter` remains responsible for Piper/pyttsx3 synthesis, faster-whisper transcription, model caches, generated audio, and workspace containment. The existing `VoiceSessionRuntime` remains the only authority for hands-free state, active-turn identity, turn completion, and barge-in/interruption.

`app/low_latency_voice_runtime_v10.py` adds the transport behavior required by v10:

- bounded synthesis chunks for earlier first-audio availability;
- safe-boundary barge-in handling;
- stale synthesis suppression after interruption;
- stale transcription suppression after session transition;
- first-audio and total-turn latency evidence;
- governed input/chunk limits;
- failure transitions that preserve the interrupted turn for explicit recovery instead of silently completing it.

## State ownership

There is no second v10 session database or session state machine.

The lifecycle remains:

1. `start_voice_session` starts the existing `VoiceSessionRuntime`.
2. `begin_voice_turn` creates the existing deterministic active turn.
3. `voice_v10_synthesize_active_turn` transitions THINKING → SPEAKING through `VoiceSessionRuntime.begin_speaking()`.
4. Successful chunk completion calls the existing `complete_turn()` and returns to LISTENING for hands-free mode or IDLE otherwise.
5. `voice_v10_interrupt` delegates directly to `VoiceSessionRuntime.interrupt()`.
6. An interrupted turn stays preserved until the existing `abandon_interrupted_voice_turn` recovery action is used.

## Interruption model

The runtime deliberately does not terminate a TTS worker thread in the middle of a Piper or system-engine call. Force-killing an engine can leave native resources or output files in an unknown state.

Instead, each response is split into bounded chunks. The runtime verifies that the same active turn is still in SPEAKING state before and after every engine call. If the existing session runtime records a barge-in while a chunk is being generated, that chunk result is treated as stale and is not admitted to the returned playback sequence. No later chunk is generated.

This gives deterministic interruption at the next safe synthesis boundary while preserving engine integrity.

## Latency evidence

Every synthesis result reports:

- requested/completed chunk counts;
- `first_audio_ms`;
- `total_elapsed_ms`;
- configured `target_first_audio_ms`;
- whether the first-audio target was met;
- per-chunk generated path, engine, adapter latency, and readiness offset.

The default first-audio target is 1500 ms. This is a readiness target, not a fabricated guarantee: the result reports the measured outcome from the actual configured local engine.

## Bounds

Default governed limits:

- maximum response input: 12,000 characters;
- maximum synthesis chunk: 220 characters;
- maximum chunks per turn: 64;
- first-audio readiness target: 1,500 ms.

Unsafe policy values are rejected during runtime construction. Oversized text is rejected before the TTS adapter is called.

## Transcription

`voice_v10_transcribe_audio` executes the existing `VoiceAdapter.transcribe` function in a worker thread so synchronous faster-whisper work does not block the async mission loop. If the voice session is stopped/restarted while transcription is in flight, the returned transcript is discarded as stale instead of being admitted into a later session state.

The underlying adapter continues to enforce workspace path containment and supported audio behavior.

## Tool and permission integration

`plugins/low_latency_voice_v10.py` attaches the runtime to the same registry-owned `VoiceAdapter` and `VoiceSessionRuntime` instances.

Registered tools:

- `voice_v10_status` — `gate="voice"`, read risk;
- `voice_v10_synthesize_active_turn` — `gate="voice"`, execute risk;
- `voice_v10_transcribe_audio` — `gate="voice"`, execute risk;
- `voice_v10_interrupt` — `gate="voice"`, execute risk.

The plugin fails closed and registers nothing if either shared voice dependency is unavailable. It never constructs a fallback session authority.

## Security and reliability properties

- Existing voice permission gates remain authoritative.
- Existing workspace containment remains authoritative for audio paths.
- No arbitrary shell, network, destructive-file, or approval-bypass capability is added.
- No engine thread is forcibly terminated.
- Interrupted and failed synthesis cannot be silently marked complete.
- Stale audio/transcript results are rejected after relevant session transitions.
- The response text and number of synthesis engine calls are bounded.
- Existing voice-engine model caches are reused rather than duplicated.

## Regression coverage

`tests/test_low_latency_voice_runtime_v10.py` covers chunking, latency evidence, safe-boundary barge-in, stale transcription, hands-free lifecycle reuse, bounded-input rejection, fail-closed synthesis failure, policy validation, and shared status reporting.

`tests/test_low_latency_voice_plugin_v10.py` verifies that the plugin uses the existing registry voice/session instances and preserves the voice gate and risk classifications.

## Remaining Batch 10 work

This checkpoint establishes the trusted interruptible transport foundation. Remaining Batch 10 work includes end-to-end API/UI integration where appropriate, latency and interruption benchmark families, release evidence, and exact-head CI/security verification.
