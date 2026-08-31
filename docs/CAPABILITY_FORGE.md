# Capability Forge

The forge is a controlled path for creating a missing local tool.

## Lifecycle

1. Stage source under `data/capability_staging`.
2. Parse and compile it.
3. Scan for missing registration, dynamic execution, and high-risk imports.
4. Review source and validation evidence.
5. Approve promotion.
6. Preserve an existing plugin before replacement.
7. Copy the validated source into `plugins`.
8. Restart DPN AI to load it.
9. Roll back from a preserved version when needed.

Staging never activates code. Promotion and rollback are destructive-risk tools and therefore require approval in Standard mode. Static checks reduce risk but are not a formal proof of safety; promoted plugins are trusted Python and must be reviewed.