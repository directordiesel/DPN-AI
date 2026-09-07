# DPN AI v10 — Professional Artifact Profiles and Release Readiness

Batch 9 extends the existing `ArtifactStudio` and `DocumentFactory` path. It does not introduce a second document-generation subsystem.

## Governed profiles

`app/artifact_profiles_v10.py` defines immutable default profiles for the four approved professional formats:

- `professional_report_docx`
- `formal_report_pdf`
- `analytical_workbook_xlsx`
- `executive_deck_pptx`

Profiles are deterministic host-side policy. Model/provider output cannot redefine profile limits or mark itself ready.

The preflight gate runs before file generation. It requires a title, at least one content item, bounded item counts, and format-specific structure. Reports require titled non-empty sections. Workbooks require unique named sheets with populated headers and bounded formulas/charts. Presentations require titled non-empty slides and no more than eight meaningful bullets per content slide.

A failed profile preflight returns `professional_ready=false` and does not write the requested output file.

## Layered professional readiness

`ArtifactStudio` now reports four independent evidence layers:

1. `profile` — request preflight against the governed professional profile;
2. `validation` — structural/container integrity plus SHA-256 evidence;
3. `quality` — format-aware parseability and professional structural checks;
4. `acceptance` — deterministic request-to-output identity verification.

`professional_ready=true` requires all four layers to pass.

## Benchmark families

`app/artifact_benchmark_v10.py` reuses the v10 Benchmark Laboratory and defines four required families:

- `artifact_docx_professional`
- `artifact_pdf_professional`
- `artifact_xlsx_professional`
- `artifact_pptx_professional`

Each family requires success rate 1.0, quality score 1.0, and at least one trusted sample. This aggregate gate is not sufficient by itself for release readiness.

## Exact release evidence

`app/artifact_release_audit_v10.py` maps every required format family to an exact end-to-end pytest node in `tests/test_artifact_release_cases_v10.py`. Every case generates a real artifact through `ArtifactStudio` and requires profile, structural validation, professional quality, request acceptance, and final professional readiness to pass.

Missing required executed-test evidence fails closed. A required failure wins even if the same test ID is also claimed as passed.

`app/artifact_release_ci_v10.py` and `.github/scripts/artifact_release_readiness_v10.py` execute exactly that immutable manifest. Callers cannot substitute arbitrary test IDs. GitHub Actions runs the Batch 9 readiness harness on Ubuntu/Python 3.11 in addition to the normal cross-platform test suite and the existing Batch 8 memory release gate.

## Security and reliability boundaries

- No destructive filesystem operation is introduced.
- Workspace containment remains enforced.
- Spreadsheet formulas are stored but never evaluated by the readiness system.
- Office macros are not executed.
- Parser/provider output cannot set readiness directly.
- Structural validity alone is insufficient for professional readiness.
- Aggregate benchmark counts cannot replace exact mandatory release evidence.
- Any missing required release case blocks readiness.

Batch 9 remains in development until the exact-head CI/security gates prove the new release harness and remaining professional artifact requirements are completed.
