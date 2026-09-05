# DPN AI v9 — Voice + Multimodal Interaction

DPN AI v9 layers deterministic hands-free session orchestration on top of the existing local Whisper/Piper voice stack.

## Runtime capabilities

- Hands-free session start/stop state
- Listening, thinking, speaking, interrupted, and idle transitions
- Barge-in interruption without deleting the active turn record
- Bounded multimodal attachments for image, audio, and document inputs
- Workspace-bound attachment resolution
- Per-turn modality metadata and sequence numbers
- Automatic return to listening after a completed hands-free turn

## Safety boundaries

- Voice session execution remains protected by the existing `voice` permission gate.
- Attachment paths must remain inside the configured DPN AI workspace.
- Unsupported attachment types and excessive attachment counts fail closed.
- The session runtime coordinates interaction state; it does not replace the existing STT/TTS engines.
