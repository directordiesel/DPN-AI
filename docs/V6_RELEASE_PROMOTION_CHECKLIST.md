# DPN AI v6.0.0 Release Promotion Checklist

- [x] v6 Advanced Core merged to `main`
- [x] Stable merge commit recorded
- [x] CI passed on validated v6 head
- [x] DPN Security Gate v2 passed
- [x] Runtime & Recovery Assurance passed
- [x] Release version promoted from 5.0.7 to 6.0.0 on the release branch
- [x] Release notes added
- [ ] Runtime-visible hard-coded 5.0.7 strings audited and promoted where they represent the current product version
- [ ] Release PR merged to `main`
- [ ] GitHub Release workflow dispatched for `v6.0.0`
- [ ] Published release assets and checksums verified

The release workflow requires `VERSION` to match the requested release tag and will reject an existing tag or tracked sensitive/runtime state.
