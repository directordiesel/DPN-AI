# Desktop Control Center Recovery Note

During the v7 desktop-control-center batch, a partial read of `app/main.py` was identified as unsafe for whole-file replacement. The intended version-source cleanup is therefore deferred to the comprehensive security/QA batch, where the complete file will be handled through a full-content or Git-object-safe update. Stable `main` is unchanged.
