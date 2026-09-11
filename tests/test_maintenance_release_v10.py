from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.maintenance_release_ci_v10 import (
    MaintenanceReleaseCIError,
    run_maintenance_release_ci,
)
from app.maintenance_release_v10 import (
    BASE_STABLE_VERSION,
    CHECKPOINT,
    MaintenanceReleaseError,
    TARGET_TAG,
    TARGET_VERSION,
    audit_maintenance_release,
    maintenance_release_manifest,
    require_maintenance_release,
    require_maintenance_version_surfaces,
)


ROOT = Path(__file__).resolve().parents[1]


def _passing_evidence() -> dict[str, bool]:
    return {family: True for family in maintenance_release_manifest()}


def test_maintenance_identity_preserves_published_stable_baseline() -> None:
    assert BASE_STABLE_VERSION == "10.0.0"
    assert TARGET_VERSION == "10.0.1"
    assert TARGET_TAG == "v10.0.1"
    assert CHECKPOINT == "v10.0.1-maintenance-readiness"


def test_maintenance_manifest_is_fixed_unique_and_nonempty() -> None:
    manifest = maintenance_release_manifest()
    assert len(manifest) == 11
    assert len(set(manifest)) == len(manifest)
    assert len(set(manifest.values())) == len(manifest)
    assert all(test_id.startswith("tests/") and "::test_" in test_id for test_id in manifest.values())


def test_complete_maintenance_evidence_is_ready_but_non_authorizing() -> None:
    audit = require_maintenance_release(_passing_evidence())
    assert audit["ready"] is True
    assert audit["checkpoint"] == CHECKPOINT
    assert audit["base_stable_version"] == BASE_STABLE_VERSION
    assert audit["target_version"] == TARGET_VERSION
    assert audit["target_tag"] == TARGET_TAG
    assert audit["execution_authorized"] is False
    assert audit["release_publish_authorized"] is False
    assert audit["missing_families"] == []
    assert audit["failed_families"] == []
    assert audit["unexpected_families"] == []


def test_missing_unexpected_failed_or_truthy_maintenance_evidence_fails_closed() -> None:
    manifest = maintenance_release_manifest()

    missing = _passing_evidence()
    missing.pop(next(iter(manifest)))
    audit = audit_maintenance_release(missing)
    assert audit["ready"] is False
    assert audit["missing_families"]
    with pytest.raises(MaintenanceReleaseError):
        require_maintenance_release(missing)

    unexpected = _passing_evidence()
    unexpected["unapproved_extra_family"] = True
    audit = audit_maintenance_release(unexpected)
    assert audit["ready"] is False
    assert audit["unexpected_families"] == ["unapproved_extra_family"]

    failed = _passing_evidence()
    failed[next(iter(manifest))] = False
    assert audit_maintenance_release(failed)["ready"] is False

    truthy = _passing_evidence()
    truthy[next(iter(manifest))] = 1
    audit = audit_maintenance_release(truthy)
    assert audit["ready"] is False
    assert audit["failed_families"]


def test_repository_candidate_version_surfaces_are_coherent() -> None:
    values = require_maintenance_version_surfaces(ROOT)
    assert values["VERSION"] == TARGET_VERSION
    assert values["app_runtime"] == TARGET_VERSION
    assert values["readme_stable"] == f"v{BASE_STABLE_VERSION}"
    assert values["readme_candidate"] == TARGET_TAG
    assert values["roadmap_stable"] == f"v{BASE_STABLE_VERSION}"
    assert values["roadmap_active"] == "v10.0.1 maintenance hardening and release-candidate validation"
    assert values["android_development_version"] == "10.0.1-dev"


def test_maintenance_ci_executes_exact_manifest_and_returns_non_authorizing_evidence(tmp_path: Path) -> None:
    calls: list[tuple[list[str], str]] = []

    def runner(command, *, cwd, text, capture_output, check):
        calls.append((list(command), cwd))
        return subprocess.CompletedProcess(command, 0, stdout="11 passed\n", stderr="")

    payload = run_maintenance_release_ci(
        runner=runner,
        python_executable="python-test",
        repository_root=tmp_path,
    )
    manifest = maintenance_release_manifest()
    assert calls == [(["python-test", "-m", "pytest", "-q", *manifest.values()], str(tmp_path.resolve()))]
    assert payload["ready"] is True
    assert payload["audit"]["execution_authorized"] is False
    assert payload["audit"]["release_publish_authorized"] is False


def test_maintenance_ci_blocks_failed_required_tests(tmp_path: Path) -> None:
    def runner(command, *, cwd, text, capture_output, check):
        return subprocess.CompletedProcess(command, 1, stdout="1 failed\n", stderr="")

    with pytest.raises(MaintenanceReleaseCIError, match="readiness blocked"):
        run_maintenance_release_ci(
            runner=runner,
            python_executable="python-test",
            repository_root=tmp_path,
        )
