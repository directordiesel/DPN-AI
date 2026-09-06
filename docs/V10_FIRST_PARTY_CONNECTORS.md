# DPN AI v10.0.0 — First-Party Connector Profiles

Batch 6 adds curated first-party HTTP connector profiles on top of the existing hardened `ConnectorHub` and DPN Connector Protocol runtime.

## Included profiles

- GitHub REST API
- Google APIs for Gmail, Calendar, and Drive REST paths
- Microsoft Graph for Outlook, Calendar, and OneDrive
- Slack Web API
- Discord REST API v10
- Reddit OAuth API

Profiles define fixed HTTPS API roots, least-necessary HTTP method sets, and vault secret references. They do not embed credentials, acquire OAuth tokens, or silently enable a provider.

## Security model

`dpn_connector_profile_catalog` is read-only and returns provider metadata plus the names of required vault secrets. It never returns header templates or secret values.

`dpn_connector_profile_install` modifies local connector configuration and is therefore forced through explicit human approval even when DPN AI is operating in autonomous/Always Allow mode. A newly installed profile is disabled by default unless the approved request explicitly enables it.

Secrets are stored separately in `SecretVault` and referenced using the existing `{{secret:name}}` syntax. At request time, `ConnectorHub` resolves those references, validates the configured host, rejects embedded credentials, blocks host escape and private/reserved destinations when private networking is disabled, refuses redirects, bounds response size, and enforces the connector's HTTP method allowlist.

External mutation still flows through `dpn_connector_write`. Create/update/delete operations require human approval and are single-attempt so ambiguous network failures cannot be automatically replayed.

## Provider-specific notes

GitHub uses `https://api.github.com/`, the GitHub JSON media type, and the pinned REST API version header. Google uses `https://www.googleapis.com/`; OAuth refresh remains outside the static profile. Microsoft uses Graph v1.0. Slack exposes GET and POST only. Discord uses REST API v10. Reddit uses the OAuth API root and a DPN AI user agent.

A profile being present does not mean the provider is ready. Readiness still depends on the connector being enabled, its vault secret existing and resolving, the configured permission gate being enabled, and the provider request succeeding with provenance.
