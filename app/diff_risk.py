from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


SENSITIVE_PREFIXES = (
    ".github/workflows/",
    "app/security",
    "app/approval",
    "app/auth",
    "app/db.py",
    "app/config.py",
    "mobile/auth",
    "mobile/device_registry",
)


@dataclass(frozen=True)
class DiffRiskFinding:
    path: str
    severity: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DiffRiskAnalyzer:
    """Deterministic pre-merge review for proposed repository diffs."""

    @staticmethod
    def analyze(files: list[dict[str, Any]]) -> dict[str, Any]:
        findings: list[DiffRiskFinding] = []
        additions = 0
        deletions = 0
        touched: list[str] = []

        for item in files:
            path = str(item.get("filename") or item.get("path") or "")
            if not path:
                continue
            touched.append(path)
            add = int(item.get("additions") or 0)
            delete = int(item.get("deletions") or 0)
            additions += add
            deletions += delete
            status = str(item.get("status") or "modified")

            if path.startswith(SENSITIVE_PREFIXES):
                findings.append(DiffRiskFinding(path, "high", "sensitive security/configuration path changed"))
            if status == "removed":
                findings.append(DiffRiskFinding(path, "medium", "file deletion requires explicit review"))
            if add + delete >= 500:
                findings.append(DiffRiskFinding(path, "medium", "large single-file change increases regression risk"))
            lower = path.lower()
            if any(token in lower for token in ("secret", "credential", "token", "private_key", "keystore")):
                findings.append(DiffRiskFinding(path, "high", "credential-adjacent path requires security review"))

        high = [f for f in findings if f.severity == "high"]
        medium = [f for f in findings if f.severity == "medium"]
        score = min(100, len(high) * 35 + len(medium) * 12 + (10 if additions + deletions >= 1500 else 0))
        level = "high" if score >= 50 else "medium" if score >= 20 else "low"
        return {
            "risk_level": level,
            "risk_score": score,
            "requires_security_review": bool(high),
            "requires_human_approval": bool(high) or any(f.reason.startswith("file deletion") for f in findings),
            "files_touched": touched,
            "additions": additions,
            "deletions": deletions,
            "findings": [f.to_dict() for f in findings],
        }
