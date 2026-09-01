# DPN Repository Certification Scorecard

**Repository:** DPN AI  
**Certification baseline:** DPN GitHub Governance v4  
**Reviewed:** 2026-09-01  
**Baseline commit:** `5370d90a2e669d955c38b1217ab0581e3612abb6`  
**Certification:** CONDITIONAL — automated controls healthy; settings enforcement remains external.

## Engineering controls

| Control | Status |
| --- | --- |
| DPN repository governance standard | PASS |
| Continuous integration | PASS |
| Runtime assurance | PASS |
| Security gate | PASS |
| Supply-chain workflow | PASS |
| Dependency automation / Dependabot | PASS |
| Release automation | PASS |
| Environment template / secret separation | PASS |
| Least-privilege workflow baseline | PASS |
| Immutable SHA-pinned core Actions | PASS |
| Branch/ruleset enforcement | BLOCKED BY INTEGRATION / PLAN |
| GitHub code scanning / CodeQL entitlement | MANUAL VERIFICATION REQUIRED |
| GitHub secret scanning / push protection | MANUAL VERIFICATION REQUIRED |

## Governance v4 certification

The audited CI and security activity on the v3 baseline completed successfully. No Critical repository-file finding was confirmed. API/model-provider credential exposure remains a release-blocking class of issue and scanner output must remain redacted.

## Outstanding governance actions

Verify protected `main`, required status checks, force-push/deletion protection, GitHub secret scanning/push protection, and CodeQL/default setup where supported. Continue credential-history auditing and strict environment-template hygiene.
