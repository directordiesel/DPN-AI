from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Iterable, Mapping

from app.self_improvement_v10 import SelfImprovementEvaluation, SelfImprovementError, SelfImprovementEvidenceStore

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ExecutedBenchmarkManifest:
    manifest_id: str
    benchmark_model_name: str
    candidate_commit_sha: str
    required_families: tuple[str, ...]
    run_ids: tuple[str, ...]
    result_digest_sha256: str
    executor_identity: str

    def normalized(self) -> "ExecutedBenchmarkManifest":
        manifest_id = self.manifest_id.strip()
        model = self.benchmark_model_name.strip()
        commit = self.candidate_commit_sha.strip().lower()
        executor = self.executor_identity.strip()
        families = tuple(sorted({str(item).strip() for item in self.required_families if str(item).strip()}))
        run_ids = tuple(sorted({str(item).strip() for item in self.run_ids if str(item).strip()}))
        digest = self.result_digest_sha256.strip().lower()
        if not manifest_id or len(manifest_id) > 120:
            raise SelfImprovementError("benchmark manifest id is required and bounded")
        if not model or len(model) > 160:
            raise SelfImprovementError("benchmark model identity is required and bounded")
        if not _SHA_RE.fullmatch(commit):
            raise SelfImprovementError("candidate commit sha must be an exact 40-character git sha")
        if not families or len(families) > 64:
            raise SelfImprovementError("benchmark manifest requires bounded task families")
        if not run_ids or len(run_ids) > 4096:
            raise SelfImprovementError("benchmark manifest requires executed run ids")
        if not _SHA256_RE.fullmatch(digest):
            raise SelfImprovementError("benchmark manifest result digest is invalid")
        if not executor or len(executor) > 160:
            raise SelfImprovementError("benchmark executor identity is required and bounded")
        return ExecutedBenchmarkManifest(manifest_id, model, commit, families, run_ids, digest, executor)

    def digest(self) -> str:
        payload = asdict(self.normalized())
        payload["required_families"] = list(payload["required_families"])
        payload["run_ids"] = list(payload["run_ids"])
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CandidateCodeBinding:
    repository: str
    candidate_commit_sha: str
    changed_paths: tuple[str, ...]
    tree_digest_sha256: str

    def normalized(self) -> "CandidateCodeBinding":
        repository = self.repository.strip()
        commit = self.candidate_commit_sha.strip().lower()
        paths = tuple(sorted({str(item).strip().replace("\\", "/") for item in self.changed_paths if str(item).strip()}))
        digest = self.tree_digest_sha256.strip().lower()
        if not repository or len(repository) > 240:
            raise SelfImprovementError("candidate repository is required and bounded")
        if not _SHA_RE.fullmatch(commit):
            raise SelfImprovementError("candidate commit sha is invalid")
        if not paths or len(paths) > 2048:
            raise SelfImprovementError("candidate changed paths are required and bounded")
        for path in paths:
            if path.startswith(("/", "../")) or "/../" in path or path.endswith("/.."):
                raise SelfImprovementError("candidate changed path escapes repository scope")
        if not _SHA256_RE.fullmatch(digest):
            raise SelfImprovementError("candidate tree digest is invalid")
        return CandidateCodeBinding(repository, commit, paths, digest)

    def digest(self) -> str:
        payload = asdict(self.normalized())
        payload["changed_paths"] = list(payload["changed_paths"])
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SelfImprovementApplicationRequest:
    candidate_digest: str
    candidate_commit_sha: str
    benchmark_manifest_digest: str
    code_binding_digest: str
    requested_action: str
    approval_required: bool = True
    execution_authorized: bool = False
    required_authority: str = "explicit_human_approval"


@dataclass(frozen=True)
class SelfImprovementRollbackRequest:
    candidate_digest: str
    deployed_commit_sha: str
    rollback_target_sha: str
    reason: str
    approval_required: bool = True
    execution_authorized: bool = False
    required_authority: str = "explicit_human_approval"


class GovernedSelfImprovement:
    """Completion authority for Batch 14.

    This class proves benchmark/code identity and emits approval-only application or
    rollback requests. It intentionally cannot edit repositories, invoke tools,
    approve requests, deploy code, or roll back code itself.
    """

    def __init__(self, evidence_store: SelfImprovementEvidenceStore) -> None:
        self.evidence_store = evidence_store

    @staticmethod
    def _require_exact_family_match(evaluation: SelfImprovementEvaluation, manifest: ExecutedBenchmarkManifest) -> None:
        if manifest.benchmark_model_name != evaluation.benchmark_model_name:
            raise SelfImprovementError("benchmark manifest model does not match evaluation")
        if tuple(manifest.required_families) != tuple(evaluation.required_families):
            raise SelfImprovementError("benchmark manifest families do not exactly match evaluation")

    def request_application(
        self,
        *,
        evaluation: SelfImprovementEvaluation,
        manifest: ExecutedBenchmarkManifest,
        code_binding: CandidateCodeBinding,
    ) -> SelfImprovementApplicationRequest:
        if not evaluation.gate_passed:
            raise SelfImprovementError("failed benchmark evaluation cannot request application")
        stored = self.evidence_store.get(evaluation.candidate_digest)
        if stored != evaluation.to_dict():
            raise SelfImprovementError("application requires exact durable evaluation evidence")
        manifest = manifest.normalized()
        code_binding = code_binding.normalized()
        self._require_exact_family_match(evaluation, manifest)
        if manifest.candidate_commit_sha != code_binding.candidate_commit_sha:
            raise SelfImprovementError("benchmark and code evidence bind different candidate commits")
        if code_binding.repository != evaluation.repository:
            raise SelfImprovementError("code binding repository does not match evaluation")
        return SelfImprovementApplicationRequest(
            candidate_digest=evaluation.candidate_digest,
            candidate_commit_sha=manifest.candidate_commit_sha,
            benchmark_manifest_digest=manifest.digest(),
            code_binding_digest=code_binding.digest(),
            requested_action="apply_candidate_through_governed_repository_runtime",
        )

    @staticmethod
    def request_rollback(
        *,
        candidate_digest: str,
        deployed_commit_sha: str,
        rollback_target_sha: str,
        reason: str,
    ) -> SelfImprovementRollbackRequest:
        candidate_digest = candidate_digest.strip().lower()
        deployed = deployed_commit_sha.strip().lower()
        target = rollback_target_sha.strip().lower()
        reason = reason.strip()
        if not _SHA256_RE.fullmatch(candidate_digest):
            raise SelfImprovementError("rollback candidate digest is invalid")
        if not _SHA_RE.fullmatch(deployed) or not _SHA_RE.fullmatch(target):
            raise SelfImprovementError("rollback commit evidence is invalid")
        if deployed == target:
            raise SelfImprovementError("rollback target must differ from deployed commit")
        if not reason or len(reason) > 2000:
            raise SelfImprovementError("rollback reason is required and bounded")
        return SelfImprovementRollbackRequest(candidate_digest, deployed, target, reason)


__all__ = [
    "CandidateCodeBinding",
    "ExecutedBenchmarkManifest",
    "GovernedSelfImprovement",
    "SelfImprovementApplicationRequest",
    "SelfImprovementRollbackRequest",
]
