# DPN AI v10.0.0 — First-Party Connector Provider Readiness

Batch 6 adds a local, secret-safe readiness check for curated first-party connector profiles.

## Security model

`FirstPartyConnectorService.readiness()` never contacts an external provider and never decrypts a credential. It reads only the SecretVault secret-name inventory and compares that metadata with each profile's declared `required_secrets` list.

A profile is reported `ready=true` only when every required secret name is present. Missing secret names are reported explicitly so operators can configure the vault without exposing secret values.

If the SecretVault cannot be read or validated, readiness fails closed with `ok=false`, `ready_count=0`, and no profile readiness claims.

## Tool surface

`dpn_connector_profile_readiness` is registered under the `connectors` gate with `risk=read`. It performs no connector installation, provider authentication, network request, or external mutation.

Profile installation remains separately gated by `dpn_connector_profile_install` and requires explicit human approval. Provider writes still flow through `dpn_connector_write`, which remains single-use approval gated and is never automatically retried.

## Readiness versus authentication

Local credential readiness is not equivalent to successful remote authentication. It proves only that required credential references can be resolved from the configured vault. Remote provider validation should be added as an explicit bounded read operation with provider-specific endpoints and must not weaken the existing approval or secret-handling boundaries.
