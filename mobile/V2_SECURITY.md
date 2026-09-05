# DPN AI Mobile v2 — Trust, Pairing, and Remote Control

Mobile v2 extends the existing DPN AI Android companion without creating a second AI runtime.

## Device trust

- A device must be paired before any mobile API operation is attempted.
- Revoked devices fail closed and remote mode is disabled.
- Local trust sessions are bounded to 24 hours.
- Remote trust sessions are bounded to 8 hours.
- Expired sessions require secure re-pairing instead of silently reusing stale credentials.
- Android stores device credentials and trust metadata through platform-protected storage backed by Android Keystore encryption.

## Remote access

- Remote mode requires a configured HTTPS gateway.
- Loopback endpoints are rejected for remote gateway configuration.
- Remote write-like operations require authenticated gateway state and explicit user-presence confirmation at the policy layer.
- Destructive/approval-sensitive operations continue to require the desktop approval boundary; mobile trust never becomes final authorization.
- Mobile does not connect directly to the DPN AI database.

## Voice

The Android voice console remains explicit foreground capture: microphone permission is requested by Android, capture begins only after the user starts it, and no background listening is introduced by v2. Voice requests are sent through the same authenticated shared DPN AI runtime and failure states remain evidence-first.

## Compatibility

The v2 trust layer is additive. Existing chat, voice, vision, file, project/task, mission, approval, notification, diagnostics, and gateway screens remain on the existing mobile client architecture.
