from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.proactive_intelligence_v10 import ActionProposal, ProactiveIntelligenceError
from app.proactive_sources_v10 import ObservationEvidence, ProactiveSourceError


@dataclass(frozen=True)
class DispatchReceipt:
    proposal_id: str
    condition_id: str
    source_id: str
    source_digest: str
    tool_name: str
    status: str
    approval_id: str | None
    result_ok: bool
    result: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProactiveProposalDispatcher:
    """Idempotent bridge from trusted proposals back into ToolRegistry.execute().

    The dispatcher has no private execution path. Every first-time proposal re-enters
    ToolRegistry.execute(), so current gate/risk policy and ApprovalSecurity remain
    authoritative. A durable receipt prevents replay after any dispatch attempt.
    """

    def __init__(self, registry: Any, receipt_path: str | Path) -> None:
        self.registry = registry
        self.receipt_path = Path(receipt_path)

    def _load(self) -> dict[str, Any]:
        if not self.receipt_path.exists():
            return {"schema_version": 1, "receipts": {}}
        try:
            payload = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProactiveIntelligenceError("proactive dispatch receipts are unreadable; dispatch blocked") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("receipts"), dict):
            raise ProactiveIntelligenceError("proactive dispatch receipt schema is invalid; dispatch blocked")
        return payload

    def _save(self, payload: dict[str, Any]) -> None:
        self.receipt_path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        temporary = self.receipt_path.with_name(self.receipt_path.name + ".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, self.receipt_path)

    @staticmethod
    def _validate_binding(proposal: ActionProposal, evidence: ObservationEvidence) -> None:
        if proposal.execution_authorized:
            raise ProactiveIntelligenceError("proposal attempted to self-authorize execution")
        if not evidence.trusted_for_dispatch:
            raise ProactiveSourceError("untrusted condition evidence cannot be dispatched")
        if proposal.source_id != evidence.source_id:
            raise ProactiveSourceError("proposal source does not match evidence source")
        if proposal.source_digest != evidence.source_digest:
            raise ProactiveSourceError("proposal source digest does not match evidence")
        if not proposal.observation_digest:
            raise ProactiveIntelligenceError("proposal is missing observation binding")

    def _validate_current_tool(self, proposal: ActionProposal) -> None:
        registered = getattr(self.registry, "tools", {}).get(proposal.tool_name)
        if registered is None:
            raise ProactiveIntelligenceError("proposed tool is no longer registered")
        current_risk = str(getattr(registered, "risk", "read"))
        current_gate = getattr(registered, "gate", None)
        if current_risk != proposal.risk or current_gate != proposal.gate:
            raise ProactiveIntelligenceError("proposed tool risk/gate metadata changed after evaluation")

    async def dispatch(
        self,
        proposal: ActionProposal,
        evidence: ObservationEvidence,
        *,
        permissions: dict[str, Any],
    ) -> DispatchReceipt:
        self._validate_binding(proposal, evidence)
        evidence.require_fresh(evidence.collected_at)
        self._validate_current_tool(proposal)
        state = self._load()
        existing = state["receipts"].get(proposal.proposal_id)
        if existing is not None:
            return DispatchReceipt(**existing)

        result = await self.registry.execute(proposal.tool_name, dict(proposal.arguments), dict(permissions))
        if not isinstance(result, dict):
            result = {"ok": False, "error": "ToolRegistry returned an invalid dispatch result"}
        approval_id = str(result.get("approval_id")) if result.get("approval_id") else None
        if result.get("approval_required"):
            status = "approval_pending"
        elif result.get("ok"):
            status = "executed"
        else:
            status = "blocked_or_failed"
        receipt = DispatchReceipt(
            proposal_id=proposal.proposal_id,
            condition_id=proposal.condition_id,
            source_id=evidence.source_id,
            source_digest=evidence.source_digest,
            tool_name=proposal.tool_name,
            status=status,
            approval_id=approval_id,
            result_ok=bool(result.get("ok")),
            result=result,
        )
        state["receipts"][proposal.proposal_id] = receipt.to_dict()
        self._save(state)
        return receipt

    def status(self) -> dict[str, Any]:
        state = self._load()
        return {
            "ok": True,
            "schema_version": state["schema_version"],
            "receipts": len(state["receipts"]),
            "execution_path": "ToolRegistry.execute -> ApprovalSecurity",
            "idempotent_replay_block": True,
        }


__all__ = ["DispatchReceipt", "ProactiveProposalDispatcher"]
