# DPN AI v10.0.1 Maintenance Release Readiness

DPN AI v10.0.1 is a maintenance candidate built on the published **v10.0.0** stable baseline. This gate does not replace, rewrite, or weaken the historical v10.0.0 Batch 18 production-release authority.

## Purpose

The v10.0.1 gate proves that the usability and reliability recovery work is integrated as a coherent patch release. It is evidence-only: a successful gate does **not** authorize execution, merge, release publication, plugin promotion, connector mutation, deployment, or approval bypass.

## Mandatory acceptance families

The fixed manifest in \`app/maintenance_release_v10.py\` requires exact pytest node IDs for:

1. desktop encoding integrity;
2. desktop DOM integrity;
3. modal accessibility and focus lifecycle;
4. actionable, bounded, redacted error recovery;
5. plain-language unavailable-capability recovery;
6. human-first technical evidence presentation;
7. Android primary-screen scrollability;
8. Android button action wiring;
9. Android safe connection recovery;
10. Android voice fallback/setup guidance;
11. active v10.0.1 candidate version-surface coherence.

Missing, failed, unexpected, or merely truthy non-boolean evidence fails closed.

## Version model

- Published stable baseline: \`v10.0.0\`
- Maintenance candidate: \`v10.0.1\`
- Android development identity: \`10.0.1-dev\`

Historical v10.0.0 Batch 8-18 checkpoints remain historical evidence and must not be renamed to v10.0.1.

The active candidate surfaces governed by the maintenance contract include \`VERSION\`, runtime identity, static cache-busters, service-worker identity, README stable/candidate identities, roadmap baseline/direction, and Android development version.

## CI

The Ubuntu / Python 3.11 CI lane executes:

\`\`\`bash
python .github/scripts/maintenance_release_readiness_v10.py
\`\`\`

The script runs the fixed mandatory pytest nodes, then performs a strict evidence audit.

Successful output must retain:

- \`ready=true\`
- \`execution_authorized=false\`
- \`release_publish_authorized=false\`

## Publication boundary

The existing manual \`.github/workflows/release.yml\` remains the only GitHub publication path. It requires an exact tag matching repository \`VERSION\`, runs the complete release test/supply-chain process from \`main\`, and refuses an existing tag.

This maintenance-readiness gate never invokes that workflow. Publishing \`v10.0.1\` remains an explicit separately authorized action.
