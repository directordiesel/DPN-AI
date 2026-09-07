from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from app.voice_benchmark_v10 import (
    VOICE_REQUIRED_FAMILIES,
    VoiceBenchmarkObservation,
    evaluate_voice_readiness,
    voice_runs,
)


VOICE_RELEASE_TEST_MANIFEST: Mapping[str, tuple[str, ...]] = {
    "voice_first_audio_latency": (
        "tests/test_low_latency_voice_runtime_v10.py::test_voice_runtime_chunks_response_and_reports_first_audio_latency",
    ),
    "voice_barge_in_correctness": (
        "tests/test_low_latency_voice_runtime_v10.py::test_voice_runtime_barge_in_reuses_session_authority_and_stops_at_safe_boundary",
    ),
    "voice_stale_result_suppression": (
        "tests/test_low_latency_voice_runtime_v10.py::test_voice_runtime_discards_transcription_after_session_stop",
    ),
    "voice_hands_free_recovery": (
        "tests/test_low_latency_voice_runtime_v10.py::test_new_voice_turn_uses_existing_hands_free_lifecycle",
    ),
    "voice_end_to_end_turn": (
        "tests/test_voice_turn_pipeline_v10.py::test_voice_turn_pipeline_runs_stt_reasoning_session_and_tts",
    ),
}


@dataclass(frozen=True)
class VoiceReleaseAuditResult:
    ready: bool
    reason: str
    required_test_ids: tuple[str, ...]
    missing_test_ids: tuple[str, ...]
    failed_test_ids: tuple[str, ...]
    passing_families: int
    failing_families: tuple[str, ...]


def required_voice_release_test_ids() -> tuple[str, ...]:
    return tuple(sorted({test_id for family in VOICE_REQUIRED_FAMILIES for test_id in VOICE_RELEASE_TEST_MANIFEST[family]}))


def audit_voice_release_evidence(
    *,
    passed_test_ids: Iterable[str],
    failed_test_ids: Iterable[str] = (),
    latency_ms_by_test: Mapping[str, int] | None = None,
) -> VoiceReleaseAuditResult:
    passed = {item.strip() for item in passed_test_ids if item and item.strip()}
    failed = {item.strip() for item in failed_test_ids if item and item.strip()}
    required = set(required_voice_release_test_ids())
    failed_required = tuple(sorted(required.intersection(failed)))
    missing = tuple(sorted(required.difference(passed).difference(failed)))
    latency_map = dict(latency_ms_by_test or {})

    observations: list[VoiceBenchmarkObservation] = []
    for family in VOICE_REQUIRED_FAMILIES:
        family_tests = VOICE_RELEASE_TEST_MANIFEST[family]
        family_passed = all(test_id in passed for test_id in family_tests)
        family_failed = any(test_id in failed for test_id in family_tests)
        observations.append(
            VoiceBenchmarkObservation(
                task_family=family,
                task_id=f"{family}:release-manifest",
                passed=family_passed and not family_failed,
                quality_score=1.0 if family_passed and not family_failed else 0.0,
                latency_ms=max((latency_map.get(test_id, 0) for test_id in family_tests), default=0),
            )
        )

    readiness = evaluate_voice_readiness(voice_runs(observations))
    ready = readiness.ready and not missing and not failed_required
    if failed_required:
        reason = "voice release audit failed: required tests failed"
    elif missing:
        reason = "voice release audit failed closed: required executed-test evidence is missing"
    elif not readiness.ready:
        reason = "voice release audit failed closed: benchmark gate did not pass"
    else:
        reason = "voice release audit passed"

    return VoiceReleaseAuditResult(
        ready=ready,
        reason=reason,
        required_test_ids=tuple(sorted(required)),
        missing_test_ids=missing,
        failed_test_ids=failed_required,
        passing_families=readiness.passing_profiles,
        failing_families=readiness.failing_profiles,
    )


__all__ = [
    "VOICE_RELEASE_TEST_MANIFEST",
    "VoiceReleaseAuditResult",
    "audit_voice_release_evidence",
    "required_voice_release_test_ids",
]
