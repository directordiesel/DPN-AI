from __future__ import annotations

import pytest

from app.production_release_v10 import ProductionReleaseError
from app.version_promotion_v10 import (
    ACTIVE_VERSION_SURFACES,
    EXPECTED_PROMOTED_VALUES,
    evaluate_version_promotion,
)


def _values() -> dict[str, str]:
    return dict(EXPECTED_PROMOTED_VALUES)


def test_active_version_surfaces_are_exact_and_non_authorizing() -> None:
    result = evaluate_version_promotion(_values())
    assert result.coherent is True
    assert result.active_surfaces == ACTIVE_VERSION_SURFACES
    assert result.target_version == "10.0.0"
    assert result.target_tag == "v10.0.0"
    assert result.execution_authorized is False
    assert result.release_publish_authorized is False
    assert len(result.evidence_digest) == 64


def test_missing_or_unexpected_active_version_surface_fails_closed() -> None:
    values = _values()
    values.pop("app_runtime")
    with pytest.raises(ProductionReleaseError, match="exact governed set"):
        evaluate_version_promotion(values)

    values = _values()
    values["historical_v9_document"] = "v9.0.0"
    with pytest.raises(ProductionReleaseError, match="exact governed set"):
        evaluate_version_promotion(values)


def test_stale_or_whitespace_normalized_active_version_fails_closed() -> None:
    values = _values()
    values["VERSION"] = "9.0.0"
    with pytest.raises(ProductionReleaseError, match="must be exactly"):
        evaluate_version_promotion(values)

    values = _values()
    values["app_runtime"] = " 10.0.0 "
    with pytest.raises(ProductionReleaseError, match="must be exactly"):
        evaluate_version_promotion(values)


def test_historical_v9_evidence_is_not_an_active_promotion_surface() -> None:
    assert all("historical" not in item for item in ACTIVE_VERSION_SURFACES)
    assert "docs/V9_STABLE_RELEASE.md" not in ACTIVE_VERSION_SURFACES
    assert "tests/test_release_engineering_v9.py" not in ACTIVE_VERSION_SURFACES


def test_promotion_digest_is_deterministic_and_surface_bound() -> None:
    first = evaluate_version_promotion(_values())
    second = evaluate_version_promotion(_values())
    assert first.evidence_digest == second.evidence_digest
