from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from app.performance_optimization_v10 import PerformanceOptimizationEvaluation, PerformanceOptimizationError


@dataclass(frozen=True)
class PerformanceEvidenceReceipt:
    schema_version: int
    candidate_id: str
    candidate_digest: str
    model_name: str
    required_families: tuple[str, ...]
    gate_passed: bool
    measurable_improvement: bool
    evaluation_digest: str
    execution_authorized: bool = False

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["required_families"] = list(self.required_families)
        return payload


class PerformanceEvidenceStore:
    """Append-only durable Batch 17 optimization evidence.

    Receipts bind the complete normalized optimization evaluation. The store never
    grants execution authority and rejects conflicting evidence for one candidate
    digest instead of silently replacing prior evidence.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @staticmethod
    def _evaluation_digest(evaluation: PerformanceOptimizationEvaluation) -> str:
        payload = evaluation.to_dict()
        payload["execution_authorized"] = False
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()

    @classmethod
    def receipt_for(cls, evaluation: PerformanceOptimizationEvaluation) -> PerformanceEvidenceReceipt:
        if evaluation.execution_authorized:
            raise PerformanceOptimizationError("optimization evidence cannot authorize execution")
        return PerformanceEvidenceReceipt(
            schema_version=1,
            candidate_id=evaluation.candidate_id,
            candidate_digest=evaluation.candidate_digest,
            model_name=evaluation.model_name,
            required_families=tuple(evaluation.required_families),
            gate_passed=bool(evaluation.gate_passed),
            measurable_improvement=bool(evaluation.measurable_improvement),
            evaluation_digest=cls._evaluation_digest(evaluation),
            execution_authorized=False,
        )

    def load(self) -> tuple[PerformanceEvidenceReceipt, ...]:
        if not self.path.exists():
            return ()
        receipts: list[PerformanceEvidenceReceipt] = []
        seen: dict[str, PerformanceEvidenceReceipt] = {}
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                    required = payload.pop("required_families")
                    if not isinstance(required, list) or not all(isinstance(item, str) and item.strip() for item in required):
                        raise ValueError("invalid required families")
                    receipt = PerformanceEvidenceReceipt(required_families=tuple(required), **payload)
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise PerformanceOptimizationError(f"invalid performance receipt at line {line_number}") from exc
                if receipt.schema_version != 1 or receipt.execution_authorized:
                    raise PerformanceOptimizationError(f"unsafe performance receipt at line {line_number}")
                existing = seen.get(receipt.candidate_digest)
                if existing is not None and existing != receipt:
                    raise PerformanceOptimizationError("conflicting durable evidence for candidate digest")
                seen[receipt.candidate_digest] = receipt
                receipts.append(receipt)
        return tuple(receipts)

    def record(self, evaluation: PerformanceOptimizationEvaluation) -> PerformanceEvidenceReceipt:
        receipt = self.receipt_for(evaluation)
        existing = self.load()
        for item in existing:
            if item.candidate_digest == receipt.candidate_digest:
                if item != receipt:
                    raise PerformanceOptimizationError("conflicting durable evidence for candidate digest")
                return item
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(receipt.to_dict(), sort_keys=True, allow_nan=False) + "\n")
        return receipt


__all__ = ["PerformanceEvidenceReceipt", "PerformanceEvidenceStore"]
