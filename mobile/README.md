# DPN AI Mobile v1

DPN AI Mobile v1 is an Android companion to the unified DPN AI desktop/runtime architecture. It is **not** a separate AI. The Android client pairs with an explicitly authorized DPN AI desktop service and uses the same projects, conversations, memory, missions, approvals, tools, agents, audit trail, and model runtime owned by the desktop/local service.

## Security model

- No direct database access from Android.
- No embedded desktop access token, API key, connector credential, or model secret in the APK.
- Pairing is explicit, short-lived, one-time, and device-scoped.
- Long-lived device credentials are generated only after a pairing proof succeeds.
- Device credentials are stored using Android platform-protected storage when the Android application layer is added.
- Remote connectivity is disabled by default and must use an authenticated encrypted gateway; mobile never exposes or binds the desktop database directly.
- Approval-required/destructive actions continue to use the existing DPN AI approval boundaries.
- Lost/revoked devices must be rejectable without rotating unrelated desktop secrets.

## Mobile v1 capabilities

1. Secure desktop pairing and device revocation.
2. Chat against the unified DPN AI conversation runtime.
3. Voice input/output using mobile capture while preserving server-side command/approval policy.
4. Camera/vision upload to the same multimodal pipeline.
5. General file upload to the same workspace/project attachment pipeline.
6. Project and task visibility.
7. Mission status and mission creation within existing policy boundaries.
8. Approval request inbox and explicit decisions.
9. Notifications for mission, approval, connection, and update events.
10. Secure remote connectivity through an explicit gateway configuration.

## Branching and release policy

Mobile development is isolated on `feature/dpn-ai-mobile-v1`, stacked on the v8 desktop platform branch until the unified desktop API contracts are stable. The mobile branch must not merge to stable `main` before the required desktop/mobile security, API, Android build, and release gates pass and Diesel explicitly authorizes a stable release merge.
