from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Mapping

from app.production_release_v10 import EXPECTED_STABLE_VERSION, ProductionReleaseError


TARGET_TAG = f"v{EXPECTED_STABLE_VERSION}"

# Only active product surfaces belong here. Historical v9 release documents and
# regression fixtures are intentionally excluded and must remain unchanged.
ACTIVE_VERSION_SURFACES: tuple[str, ...] = (
    "VERSION",
    "app_runtime",
    "readme_stable_identity",
    "service_worker_cache",
    "static_index_assets",
    "static_app_service_worker",
    "roadmap_current_baseline",
)

EXPECTED_PROMOTED_VALUES: dict[str, str] = {
    "VERSION": EXPECTED_STABLE_VERSION,
    "app_runtime": EXPECTED_STABLE_VERSION,
    "readme_stable_identity": TARGET_TAG,
    "service_worker_cache": TARGET_TAG,
    "static_index_assets": EXPECTED_STABLE_VERSION,
    "static_app_service_worker": EXPECTED_STABLE_VERSION,
    "roadmap_current_baseline": TARGET_TAG,
}


@dataclass(frozen=True)
class VersionPromotionEvaluation:
    schema_version: int
    target_version: str
    target_tag: str
    active_surfaces: tuple[str, ...]
    evidence_digest: str
    coherent: bool
    execution_authorized: bool = False
    release_publish_authorized: bool = False

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["active_surfaces"] = list(self.active_surfaces)
        return payload


def evaluate_version_promotion(active_values: Mapping[str, object]) -> VersionPromotionEvaluation:
    if not isinstance(active_values, Mapping):
        raise ProductionReleaseError("active version evidence must be a mapping")
    actual = set(active_values)
    expected = set(ACTIVE_VERSION_SURFACES)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        raise ProductionReleaseError(
            f"active version evidence must contain the exact governed set; missing={missing}, unexpected={unexpected}"
        )

    normalized: dict[str, str] = {}
    for surface in ACTIVE_VERSION_SURFACES:
        value = active_values[surface]
        if not isinstance(value, str):
            raise ProductionReleaseError(f"active version evidence for {surface} must be a string")
        expected_value = EXPECTED_PROMOTED_VALUES[surface]
        if value != expected_value:
            raise ProductionReleaseError(
                f"active version surface {surface} must be exactly {expected_value!r}"
            )
        normalized[surface] = value

    digest_payload = {
        "schema_version": 1,
        "target_version": EXPECTED_STABLE_VERSION,
        "target_tag": TARGET_TAG,
        "active_values": normalized,
    }
    digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return VersionPromotionEvaluation(
        schema_version=1,
        target_version=EXPECTED_STABLE_VERSION,
        target_tag=TARGET_TAG,
        active_surfaces=ACTIVE_VERSION_SURFACES,
        evidence_digest=digest,
        coherent=True,
        execution_authorized=False,
        release_publish_authorized=False,
    )


__all__ = [
    "ACTIVE_VERSION_SURFACES",
    "EXPECTED_PROMOTED_VALUES",
    "TARGET_TAG",
    "VersionPromotionEvaluation",
    "evaluate_version_promotion",
]
