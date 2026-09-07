import pytest

from app.performance_optimization_v10 import PerformanceOptimizationError
from app.performance_profiles_v10 import PROFILES, get_performance_profile


def test_profiles_are_valid_and_non_authorizing_policies() -> None:
    assert {"balanced_platform", "interactive_latency", "agent_efficiency"} <= set(PROFILES)
    for profile in PROFILES.values():
        profile.validate()
        assert profile.required_families
        assert profile.policy.require_measurable_improvement is True


def test_unknown_profile_fails_closed() -> None:
    with pytest.raises(PerformanceOptimizationError):
        get_performance_profile("not-real")


def test_non_string_profile_identity_fails_closed() -> None:
    with pytest.raises(PerformanceOptimizationError):
        get_performance_profile(123)  # type: ignore[arg-type]
