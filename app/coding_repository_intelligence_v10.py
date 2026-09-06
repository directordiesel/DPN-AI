from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Iterable, Mapping


class CodingRepositoryError(ValueError):
    """Raised when repository intelligence evidence is invalid or incomplete."""


class DiffRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class RepositoryFile:
    path: str
    size: int = 0
    language: str = ""
    imports: tuple[str, ...] = ()

    def normalized_path(self) -> str:
        raw = self.path.replace("\\", "/").strip("/")
        if not raw or raw.startswith("../") or "/../" in raw:
            raise CodingRepositoryError("repository path must remain inside the repository")
        if self.size < 0:
            raise CodingRepositoryError("repository file size must be non-negative")
        return str(PurePosixPath(raw))


@dataclass(frozen=True)
class RepositoryMap:
    files: tuple[RepositoryFile, ...]

    @classmethod
    def build(cls, files: Iterable[RepositoryFile]) -> "RepositoryMap":
        seen: dict[str, RepositoryFile] = {}
        for file in files:
            path = file.normalized_path()
            if path in seen:
                raise CodingRepositoryError(f"duplicate repository path: {path}")
            seen[path] = RepositoryFile(path, file.size, file.language.strip(), tuple(file.imports))
        return cls(tuple(seen[path] for path in sorted(seen)))

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(file.path for file in self.files)

    def contains(self, path: str) -> bool:
        normalized = str(PurePosixPath(path.replace("\\", "/").strip("/")))
        return normalized in set(self.paths)


@dataclass(frozen=True)
class ChangeImpact:
    changed_files: tuple[str, ...]
    directly_affected_tests: tuple[str, ...]
    impacted_modules: tuple[str, ...]
    missing_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class RiskFinding:
    code: str
    severity: DiffRisk
    path: str
    reason: str


@dataclass(frozen=True)
class DiffRiskAssessment:
    risk: DiffRisk
    findings: tuple[RiskFinding, ...]
    approval_required: bool


@dataclass(frozen=True)
class PullRequestEvidence:
    repository_mapped: bool
    changed_files: tuple[str, ...]
    selected_tests: tuple[str, ...]
    validation_passed: bool
    self_review_passed: bool
    security_review_passed: bool
    ci_passed: bool
    diff_risk: DiffRisk
    unresolved_findings: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return (
            self.repository_mapped
            and bool(self.changed_files)
            and self.validation_passed
            and self.self_review_passed
            and self.security_review_passed
            and self.ci_passed
            and not self.unresolved_findings
            and self.diff_risk != DiffRisk.CRITICAL
        )


class RepositoryIntelligence:
    """Deterministic repository evidence for the v10 autonomous coding runtime.

    This layer never invents files or tests. It operates only on a supplied repository
    map and fails closed when requested change paths are absent.
    """

    _critical_names = {
        ".github/workflows",
        ".github/actions",
        "security",
        "auth",
        "secrets",
        "permissions",
        "installer",
        "release",
    }

    @staticmethod
    def analyze_change_impact(repo: RepositoryMap, changed_files: Iterable[str]) -> ChangeImpact:
        requested = tuple(dict.fromkeys(str(PurePosixPath(p.replace("\\", "/").strip("/"))) for p in changed_files if p.strip()))
        if not requested:
            raise CodingRepositoryError("at least one changed file is required")

        known = set(repo.paths)
        missing = tuple(path for path in requested if path not in known)
        existing = tuple(path for path in requested if path in known)

        stems = {PurePosixPath(path).stem.removeprefix("test_") for path in existing}
        tests: list[str] = []
        impacted_modules: set[str] = set()

        for file in repo.files:
            path = file.path
            if path.startswith("tests/") or "/tests/" in path:
                test_stem = PurePosixPath(path).stem.removeprefix("test_")
                if any(stem and (stem == test_stem or stem in test_stem or test_stem in stem) for stem in stems):
                    tests.append(path)
            if file.path in existing:
                module = str(PurePosixPath(file.path).parent)
                impacted_modules.add(module if module != "." else "root")

        return ChangeImpact(
            changed_files=existing,
            directly_affected_tests=tuple(sorted(dict.fromkeys(tests))),
            impacted_modules=tuple(sorted(impacted_modules)),
            missing_paths=missing,
        )

    @classmethod
    def classify_diff_risk(
        cls,
        changed_files: Iterable[str],
        *,
        added_lines: int = 0,
        deleted_lines: int = 0,
        security_findings: Iterable[RiskFinding] = (),
    ) -> DiffRiskAssessment:
        if added_lines < 0 or deleted_lines < 0:
            raise CodingRepositoryError("diff line counts must be non-negative")

        paths = tuple(dict.fromkeys(p.replace("\\", "/").strip("/") for p in changed_files if p.strip()))
        if not paths:
            raise CodingRepositoryError("at least one changed file is required for risk classification")

        findings = list(security_findings)
        highest = DiffRisk.LOW
        order = {DiffRisk.LOW: 0, DiffRisk.MEDIUM: 1, DiffRisk.HIGH: 2, DiffRisk.CRITICAL: 3}

        for path in paths:
            lower = path.lower()
            if any(marker in lower for marker in cls._critical_names):
                finding = RiskFinding("sensitive-path", DiffRisk.HIGH, path, "change touches security, release, installer, permissions, or workflow surface")
                findings.append(finding)
            elif path.endswith(("requirements.txt", "requirements-dev.txt", "pyproject.toml")):
                findings.append(RiskFinding("dependency-surface", DiffRisk.MEDIUM, path, "dependency or build metadata changed"))

        churn = added_lines + deleted_lines
        if churn >= 1000:
            findings.append(RiskFinding("large-diff", DiffRisk.HIGH, "*", "diff exceeds 1000 changed lines"))
        elif churn >= 300:
            findings.append(RiskFinding("medium-diff", DiffRisk.MEDIUM, "*", "diff exceeds 300 changed lines"))

        for finding in findings:
            if order[finding.severity] > order[highest]:
                highest = finding.severity

        return DiffRiskAssessment(
            risk=highest,
            findings=tuple(findings),
            approval_required=highest in {DiffRisk.HIGH, DiffRisk.CRITICAL},
        )

    @staticmethod
    def build_pr_evidence(
        *,
        impact: ChangeImpact,
        risk: DiffRiskAssessment,
        validation_passed: bool,
        self_review_passed: bool,
        security_review_passed: bool,
        ci_passed: bool,
        unresolved_findings: Iterable[str] = (),
    ) -> PullRequestEvidence:
        if impact.missing_paths:
            unresolved = tuple(unresolved_findings) + tuple(f"missing:{path}" for path in impact.missing_paths)
        else:
            unresolved = tuple(unresolved_findings)
        return PullRequestEvidence(
            repository_mapped=True,
            changed_files=impact.changed_files,
            selected_tests=impact.directly_affected_tests,
            validation_passed=bool(validation_passed),
            self_review_passed=bool(self_review_passed),
            security_review_passed=bool(security_review_passed),
            ci_passed=bool(ci_passed),
            diff_risk=risk.risk,
            unresolved_findings=unresolved,
        )


__all__ = [
    "ChangeImpact",
    "CodingRepositoryError",
    "DiffRisk",
    "DiffRiskAssessment",
    "PullRequestEvidence",
    "RepositoryFile",
    "RepositoryIntelligence",
    "RepositoryMap",
    "RiskFinding",
]
