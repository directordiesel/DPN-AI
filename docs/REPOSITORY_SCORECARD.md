# DPN Repository Certification Scorecard

**Repository:** DPN AI  
**Certification baseline:** DPN GitHub Governance v3  
**Reviewed:** 2026-09-01

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
| Branch/ruleset enforcement | MANUAL VERIFICATION REQUIRED |
| GitHub code scanning / CodeQL entitlement | MANUAL VERIFICATION REQUIRED |
| GitHub secret scanning / push protection | MANUAL VERIFICATION REQUIRED |

## Outstanding governance actions

Verify protected `main`, required checks, force-push/deletion protection, GitHub secret scanning/push protection, and CodeQL/default setup where supported. Continue treating API/provider credential exposure and credential-history auditing as high-priority release blockers.
