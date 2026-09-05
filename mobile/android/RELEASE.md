# DPN AI Mobile Release Readiness

DPN AI Mobile releases are intentionally fail-closed. Source control contains no keystore, signing passwords, or production signing secrets.

## Required production inputs

Supply these outside the repository through local Gradle properties or protected CI secret injection:

- `DPN_MOBILE_VERSION_CODE` — positive integer.
- `DPN_MOBILE_VERSION_NAME` — semantic version such as `1.0.0`.
- `DPN_MOBILE_KEYSTORE` — path to the private release keystore available only in the trusted build environment.
- `DPN_MOBILE_STORE_PASSWORD` — release keystore password.
- `DPN_MOBILE_KEY_ALIAS` — release key alias.
- `DPN_MOBILE_KEY_PASSWORD` — release key password.

Never commit a keystore, signing password, private key, generated signed APK/AAB, or secret-bearing Gradle property file.

## Required gates before any public release

1. `python -m unittest discover -s tests -p 'test_mobile_*.py'`
2. Android debug build succeeds.
3. Android lint succeeds with warnings treated as errors.
4. `:app:verifyReleaseReadiness` succeeds in the trusted signing environment.
5. Release APK/AAB is produced from the intended immutable commit.
6. Package identity, version code, version name, min/target SDK, backup policy, cleartext policy, and exported activities are inspected.
7. Signing certificate fingerprint is recorded and independently verified.
8. The release artifact hash is recorded before distribution.
9. Existing DPN AI backend security, approval, remote-access, and mobile regression gates are green.
10. Stable release publication requires explicit authorization from Diesel.

## Current development behavior

Without explicit production version/signing properties, the app remains a development build (`1.0.0-dev`) and the production release-readiness task fails closed. This is intentional.
