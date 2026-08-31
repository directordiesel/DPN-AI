# DPN Technology Release Process

This document defines the minimum release discipline for **DPN AI**.

## Prepare
1. Merge approved changes into the intended release branch.
2. Update `VERSION` and all applicable application-visible version locations.
3. Update `README.md`, `CHANGELOG.md`, and affected architecture/security/recovery documentation.
4. Confirm no live credentials, databases, vault keys, runtime state, private workspace files, or private exports are tracked.

## Validate
- Main CI passes.
- Full pytest suite passes.
- Python source compilation passes.
- `VERSION` and README release information agree.
- Tool-risk/approval behavior is reviewed when affected.
- Workspace/sandbox boundaries remain intact.
- Connector/MCP/plugin changes are reviewed for least privilege.
- Recovery/checkpoint impact is reviewed.

## Tag
After validation:

```bash
git checkout main
git pull --ff-only
git tag -a <version> -m "DPN AI <version>"
git push origin <version>
```

## GitHub Release
Create a GitHub Release from the approved tag and include major features, fixes, security changes, model/tool changes, breaking changes, migration steps, known limitations, and rollback notes.

Attach only approved distributable artifacts. Do not attach vault keys, private workspace data, runtime databases, credentials, or private logs.

## Hotfixes
Reproduce the defect, add regression coverage where possible, make the smallest safe correction, pass CI, increment `VERSION`, update changelog/release notes, and publish a new tag/release rather than silently replacing an existing release.
