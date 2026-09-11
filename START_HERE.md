# Start Here - DPN AI v10.0.1

DPN AI v10.0.1 is the active maintenance candidate built on the published v10.0.0 platform.

## Windows installation

1. Extract the complete repository or release package to a writable folder. Do not run the installer from inside a ZIP preview.
2. Run:

```text
install_windows.bat
```

The installer reads the current version from `VERSION`, builds or repairs the isolated Python environment, installs required dependencies, validates the application core, and preserves an existing `.env` file.

For a core-only installation without model or voice downloads, run:

```text
install_core_only_windows.bat
```

## Start DPN AI

Run:

```text
run_dpn_ai.bat
```

The local Control Center is normally available at:

```text
http://127.0.0.1:8787
```

Local-only API access remains restricted to loopback. Configure a strong `DPN_ACCESS_TOKEN` before enabling non-loopback API access.

## Repair or diagnose

Repair the installation:

```text
repair_windows.bat
```

Run diagnostics:

```text
doctor_windows.bat
```

Diagnostic and installer logs are written under `runtime_logs` and `install_logs`. Do not post logs publicly until they have been reviewed for sensitive information.

## Local AI

Ollama is the default local model provider. DPN AI can also use an explicitly configured OpenAI-compatible endpoint.

Provider credentials belong in **Connectors & Secrets**. System Settings stores only the name of the encrypted SecretVault entry, not the credential value itself.

## Voice

Optional local voice support can be installed through the main installer or later with the voice installation scripts. The Sentinel HD helper reads the application version from `VERSION` and does not represent a separate legacy release line.

## Android

The Android client requires HTTPS, secure pairing, device-scoped credentials, and the DPN AI desktop/mobile authorization boundary. Credentials are protected with Android Keystore AES-256/GCM and authenticated mobile requests are validated against the desktop device registry.

## Before reporting a problem

Use the version shown in DPN AI or the repository `VERSION` file. Include sanitized reproduction steps and never publish access tokens, API keys, vault material, device credentials, private prompts, or sensitive local paths.
