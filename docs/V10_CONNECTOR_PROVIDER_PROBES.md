# DPN AI v10.0.0 — First-Party Provider Authentication Probes

Batch 6 adds bounded remote authentication checks for curated first-party HTTP connector profiles without weakening the DPN Connector Protocol write boundary.

## Security model

`dpn_connector_profile_probe` is an external read operation. It performs at most one HTTP request and only to a fixed, curated GET endpoint associated with the selected provider profile. The caller cannot supply a URL, path, method, body, query string, or headers.

Before any network call, the service requires all of the following:

- the profile is known and explicitly supports a safe GET probe;
- the required SecretVault secret names are present;
- the configured connector exists, is enabled, and is HTTP;
- the connector base URL exactly matches the curated provider profile;
- the configured header templates exactly match the curated profile, including vault references;
- GET remains allow-listed on the live connector configuration.

The request then executes through the existing hardened `ConnectorHub`, which performs its normal URL, host, redirect, method, private-network, timeout, and SecretVault checks.

## Data minimization

Provider response bodies are never returned by the probe. The result is reduced to bounded status metadata:

- profile ID;
- connector ID;
- reachability;
- authenticated true/false;
- coarse state (`authenticated`, `rejected`, or `provider_error`);
- HTTP status code.

Network exceptions and provider payloads are not surfaced to callers. Secret values are not fetched during preflight; they are resolved only by `ConnectorHub` at request execution time.

## Supported probes

| Profile | Fixed probe | Method |
| --- | --- | --- |
| GitHub | `user` | GET |
| Google APIs | `oauth2/v3/userinfo` | GET |
| Microsoft Graph | `me` | GET |
| Discord | `users/@me` | GET |
| Reddit OAuth API | `api/v1/me` | GET |
| Slack | disabled | — |

Slack is intentionally not remotely probed in this checkpoint because the conventional Slack `auth.test` operation is POST-based. DPN AI does not reinterpret that POST as a harmless read merely to gain coverage; doing so would undermine the method-derived connector safety model.

## Retry and side-effect policy

Provider authentication probes are single-attempt. There is no automatic retry loop. They never invoke `dpn_connector_write`, never send caller-controlled request bodies, and never perform create/update/delete operations.

## Test coverage

`tests/test_dpn_connector_provider_probe_v10.py` verifies fixed GET execution, timeout clamping, response-body suppression, secret-metadata preflight, connector/profile binding, authentication-template integrity, rejected-credential handling, and Slack fail-closed behavior. The connector plugin regression suite pins the probe tool to `gate=connectors` and `risk=external`.
