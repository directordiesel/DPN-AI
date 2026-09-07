from __future__ import annotations

from dataclasses import dataclass

from app.performance_optimization_v10 import PerformanceOptimizationError, PerformanceOptimizationPolicy


@dataclass(frozen=True)
class PerformanceProfile:
    profile_id: str
    required_families: tuple[str, ...]
    policy: PerformanceOptimizationPolicy

    def validate(self) -> None:
        if not isinstance(self.profile_id, str) or not self.profile_id.strip():
            raise PerformanceOptimizationError("performance profile_id is required")
        if not self.required_families:
            raise PerformanceOptimizationError("performance profile requires benchmark families")
        if len(set(self.required_families)) != len(self.required_families):
            raise PerformanceOptimizationError("performance profile contains duplicate benchmark families")
        if not all(isinstance(item, str) and item.strip() for item in self.required_families):
            raise PerformanceOptimizationError("performance profile benchmark families must be non-empty strings")
        self.policy.validate()


PROFILES: dict[str, PerformanceProfile] = {
    "balanced_platform": PerformanceProfile(
        profile_id="balanced_platform",
        required_families=(
            "model_intelligence",
            "autonomous_coding",
            "multimodal",
            "memory",
            "artifacts",
            "voice",
            "proactive",
            "specialist",
            "marketplace",
            "self_improvement",
        ),
        policy=PerformanceOptimizationPolicy(),
    ),
    "interactive_latency": PerformanceProfile(
        profile_id="interactive_latency",
        required_families=("model_intelligence", "multimodal", "voice", "proactive"),
        policy=PerformanceOptimizationPolicy(
            max_latency_regression_ratio=0.0,
            max_retry_regression=0,
            max_token_regression_ratio=0.05,
        ),
    ),
    "agent_efficiency": PerformanceProfile(
        profile_id="agent_efficiency",
        required_families=("autonomous_coding", "memory", "specialist", "self_improvement"),
        policy=PerformanceOptimizationPolicy(
            max_latency_regression_ratio=0.05,
            max_retry_regression=0,
            max_token_regression_ratio=0.0,
        ),
    ),
}

for _profile in PROFILES.values():
    _profile.validate()


def get_performance_profile(profile_id: str) -> PerformanceProfile:
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise PerformanceOptimizationError("performance profile_id is required")
    try:
        return PROFILES[profile_id.strip()]
    except KeyError as exc:
        raise PerformanceOptimizationError("unknown performance profile") from exc


__all__ = ["PROFILES", "PerformanceProfile", "get_performance_profile"]
