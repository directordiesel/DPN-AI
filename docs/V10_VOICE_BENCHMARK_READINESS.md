# DPN AI v10.0.0 — Batch 10 Voice Benchmark & Release Readiness

Batch 10 readiness is evidence-driven and fail-closed. The low-latency voice runtime must satisfy five mandatory benchmark families before release readiness can be claimed:

1. `voice_first_audio_latency`
2. `voice_barge_in_correctness`
3. `voice_stale_result_suppression`
4. `voice_hands_free_recovery`
5. `voice_end_to_end_turn`

The end-to-end family exercises the governed `VoiceTurnPipeline`, which composes the existing speech-to-text adapter, an injected reasoning callback, the existing `VoiceSessionRuntime`, and bounded chunked text-to-speech. It does not create a competing session state machine or model execution subsystem.

## Exact release evidence

`app/voice_release_audit_v10.py` maps each required family to an exact pytest node ID. Missing mandatory execution evidence fails closed, and a required failed test blocks readiness even if the same ID is incorrectly included in a passed set.

`app/voice_release_ci_v10.py` obtains test IDs only from the immutable manifest, executes those exact tests, and produces ready evidence only after pytest exits successfully and the strict release audit passes.

`.github/scripts/voice_release_readiness_v10.py` is the CI entrypoint. The GitHub-hosted Ubuntu/Python 3.11 lane runs this gate after the full repository test suite and the Batch 8/9 release gates.

## Security and reliability boundaries

- No model/provider can assert release readiness.
- No caller can substitute arbitrary test IDs in the CI gate.
- Interrupted or stale voice results cannot be promoted to success.
- Barge-in remains owned by the existing voice-session authority.
- No forced thread termination is introduced.
- No shell, network, destructive filesystem, or approval bypass capability is added.
- The benchmark laboratory requires 1.0 success and 1.0 quality for every mandatory family.
