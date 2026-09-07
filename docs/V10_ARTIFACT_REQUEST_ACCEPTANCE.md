# DPN AI v10 — Professional Artifact Request Acceptance

Batch 9 adds a deterministic request-to-output acceptance gate for DOCX, PDF, XLSX, and PPTX artifacts. Structural validity and general professional quality are necessary but are not sufficient: DPN AI must also verify that the generated artifact contains the specific content identities requested by the generation call.

## Three independent gates

`ArtifactStudio` now reports three independent forms of evidence:

1. `validation` — file/container integrity and SHA-256 evidence;
2. `quality` — format-aware professional quality inspection;
3. `acceptance` — deterministic verification that required request identities are present in the generated artifact.

`professional_ready` is true only when all three gates pass.

## Required request identities

The acceptance gate derives required items from trusted generation arguments rather than from model-written completion prose.

- DOCX: document title plus every requested section heading.
- PDF: report title plus every requested section heading.
- XLSX: requested sheet names plus populated first-row header values.
- PPTX: presentation title plus every requested slide title.

Required identities are normalized and deduplicated, then compared case-insensitively against values parsed back from the produced artifact.

## Fail-closed behavior

Acceptance fails when a required identity is missing, when no required acceptance items are supplied, when the artifact cannot be parsed, when the file is missing, when the format is unsupported, or when the target escapes the configured workspace. A structurally valid file with omitted required content therefore cannot be promoted to `professional_ready=true`.

The gate does not use model judgment, fuzzy semantic matching, or caller-supplied success flags. It verifies concrete requested identities against the actual generated file.

## Security and reliability boundaries

- no destructive filesystem action is added;
- workspace containment is enforced before parsing;
- no macros or formulas are executed;
- XLSX reads formula text only;
- no external services are called;
- parser errors become explicit non-acceptance rather than implicit success;
- the generator remains the existing `DocumentFactory`/`ArtifactStudio` path, avoiding a duplicate artifact subsystem.

## Tests

`tests/test_artifact_acceptance_v10.py` covers successful request acceptance for all four professional formats, missing-required-content rejection, and workspace-escape rejection.
