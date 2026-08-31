from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from app.config import Settings
from app.cognitive_kernel import CognitiveKernel, GoalContract
from app.db import Database
from app.ollama_client import OllamaClient


PLANNER_PROMPT = """You are the DPN AI v5 mission architect. Turn the supplied goal contract into a compact dependency-aware execution graph.
Return only valid JSON with this shape:
{"summary":"...","steps":[{"title":"...","role":"director|software|fivem|research|business|documents|media|automation|security|computer|data|science|creative","instructions":"...","dependencies":[0],"evidence_required":["..."],"max_attempts":2,"rollback":"..."}],"success_criteria":["..."]}
Rules:
- Use 2-10 steps unless the objective is genuinely simple.
- Dependencies use zero-based earlier step indexes and must form an acyclic graph.
- Every step must produce or verify a concrete result.
- Include an inspection step before modification and an independent validation step after execution.
- State exact evidence requirements and a safe rollback for mutating steps.
- Do not duplicate work."""

REVIEWER_PROMPT = """You are an independent DPN AI verifier. Evaluate the goal contract and evidence from a deliberately skeptical perspective.
Return only JSON:
{"verdict":"pass|partial|fail","confidence":0.0,"summary":"...","verified":["..."],"missing":["..."],"contradictions":["..."],"recommended_next_actions":["..."]}
Do not treat model-written claims as proof. Prefer tool traces, test results, file existence, hashes, screenshots, and attributable sources."""


class MissionOrchestrator:
    def __init__(self, settings: Settings, db: Database, ollama: OllamaClient, agent: Any):
        self.settings = settings
        self.db = db
        self.ollama = ollama
        self.agent = agent
        agent_tools = getattr(agent, "tools", None)
        self.cognitive: CognitiveKernel = getattr(agent_tools, "cognitive", None) or CognitiveKernel(
            db, Path(getattr(settings, "workspace_dir", db.path.parent))
        )

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        text = text.strip()
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None

    @staticmethod
    def fallback_plan(objective: str) -> dict[str, Any]:
        lower = objective.lower()
        role = "director"
        if any(word in lower for word in ("fivem", "qbcore", "lua", "fxmanifest")):
            role = "fivem"
        elif any(word in lower for word in ("code", "app", "script", "server", "debug", "api")):
            role = "software"
        elif any(word in lower for word in ("document", "pdf", "spreadsheet", "presentation")):
            role = "documents"
        elif any(word in lower for word in ("research", "latest", "compare")):
            role = "research"
        elif any(word in lower for word in ("screen", "desktop", "browser", "click")):
            role = "computer"
        elif any(word in lower for word in ("data", "csv", "statistics", "analytics")):
            role = "data"
        return {
            "summary": "Inspect, execute, validate, repair if necessary, and package the requested operation.",
            "steps": [
                {
                    "title": "Inspect state and establish acceptance evidence", "role": "director",
                    "instructions": "Inspect available context and workspace state. Confirm concrete acceptance criteria, dependencies, risks, and the exact evidence required before modification.",
                    "dependencies": [], "evidence_required": ["current-state inventory", "acceptance criteria", "identified constraints"],
                    "max_attempts": 2, "rollback": "No mutation should occur during inspection.",
                },
                {
                    "title": "Execute the primary work", "role": role, "instructions": objective,
                    "dependencies": [0], "evidence_required": ["working output", "exact artifact paths", "tool or test evidence"],
                    "max_attempts": 2, "rollback": "Restore the pre-change snapshot or revert exact modified files.",
                },
                {
                    "title": "Independently validate and package results", "role": "security",
                    "instructions": "Inspect outputs independently, run available checks, verify files and claims, identify limitations, and package exact deliverable paths and evidence.",
                    "dependencies": [1], "evidence_required": ["validation output", "verified artifacts", "limitations"],
                    "max_attempts": 2, "rollback": "Do not alter valid deliverables unless a verified defect requires repair.",
                },
            ],
            "success_criteria": ["Requested deliverables exist", "Available validation passes", "Limitations are disclosed"],
        }

    async def plan(self, contract: GoalContract, model: str, think: bool | str = "medium", max_steps: int | None = None) -> dict[str, Any]:
        max_steps = max_steps or self.settings.max_mission_steps
        payload = self.cognitive.compact_context(contract)
        try:
            response = await self.ollama.chat(
                model=model,
                messages=[{"role": "system", "content": PLANNER_PROMPT}, {"role": "user", "content": payload}],
                think=think,
            )
            content = str((response.get("message") or {}).get("content") or "")
            parsed = self._extract_json(content)
            if parsed:
                return self.cognitive.normalize_plan(parsed, contract, max_steps)
        except Exception:
            pass
        return self.cognitive.normalize_plan(self.fallback_plan(contract.objective), contract, max_steps)

    async def review(self, contract: GoalContract | str, evidence: list[dict[str, Any]], model: str,
                     think: bool | str = "medium", perspective: str = "security") -> dict[str, Any]:
        # Direct-chat verification historically passed the raw user objective here.
        # Normalize it into a GoalContract so reviewer failures never become an
        # unhandled AttributeError after the main response was already generated.
        if isinstance(contract, str):
            contract = self.cognitive.derive_contract(contract)
        try:
            payload = json.dumps(
                {"perspective": perspective, "goal_contract": contract.to_dict(), "evidence": evidence},
                ensure_ascii=False, default=str,
            )
            if len(payload) > 120_000:
                payload = payload[:120_000]
            response = await self.ollama.chat(
                model=model,
                messages=[
                    {"role": "system", "content": REVIEWER_PROMPT + f"\nReviewer perspective: {perspective}."},
                    {"role": "user", "content": payload},
                ],
                think=think,
            )
            parsed = self._extract_json(str((response.get("message") or {}).get("content") or ""))
            if parsed and parsed.get("verdict") in {"pass", "partial", "fail"}:
                parsed["evaluator"] = perspective
                return parsed
        except Exception as exc:  # noqa: BLE001
            return {
                "verdict": "partial", "confidence": 0.2, "summary": f"{perspective.title()} reviewer unavailable.",
                "verified": [], "missing": [str(exc)], "contradictions": [], "recommended_next_actions": [],
                "evaluator": perspective,
            }
        return {
            "verdict": "partial", "confidence": 0.2, "summary": f"{perspective.title()} reviewer returned no structured verdict.",
            "verified": [], "missing": [], "contradictions": [], "recommended_next_actions": [], "evaluator": perspective,
        }

    @staticmethod
    def _consensus(reports: list[dict[str, Any]]) -> dict[str, Any]:
        score_map = {"fail": 0.0, "partial": 0.5, "pass": 1.0}
        weighted = []
        for report in reports:
            base = score_map.get(str(report.get("verdict")), 0.5)
            confidence = max(0.1, min(float(report.get("confidence", 0.5)), 1.0))
            weight = 1.5 if report.get("evaluator") == "deterministic" else 1.0
            weighted.append((base * confidence * weight, confidence * weight))
        score = sum(item[0] for item in weighted) / max(0.001, sum(item[1] for item in weighted))
        verdict = "pass" if score >= 0.78 else "partial" if score >= 0.34 else "fail"
        missing = []
        contradictions = []
        verified = []
        actions = []
        for report in reports:
            missing.extend(str(item) for item in report.get("missing", report.get("issues", [])) if item)
            contradictions.extend(str(item) for item in report.get("contradictions", []) if item)
            verified.extend(str(item) for item in report.get("verified", []) if item)
            actions.extend(str(item) for item in report.get("recommended_next_actions", []) if item)
        return {
            "verdict": verdict, "confidence": round(score, 2),
            "summary": f"Review quorum reached {verdict} with a weighted confidence score of {score:.2f}.",
            "verified": list(dict.fromkeys(verified))[:50], "missing": list(dict.fromkeys(missing))[:50],
            "contradictions": list(dict.fromkeys(contradictions))[:50],
            "recommended_next_actions": list(dict.fromkeys(actions))[:30], "evaluators": reports,
        }

    async def _execute_step(self, mission_id: str, objective: str, contract: GoalContract, step: dict[str, Any],
                            conversation_id: str, project_id: str | None, attachments: list[str] | None,
                            selected_think: bool | str, worker_model: str, effective: dict[str, Any]) -> tuple[dict[str, Any], int]:
        dependencies = [self.db.get_mission_step(dep) for dep in step.get("dependencies", [])]
        context = "\n\n".join(
            f"Completed dependency: {dep['title']}\nResult: {json.dumps(dep.get('result', {}), ensure_ascii=False, default=str)[:20000]}"
            for dep in dependencies if dep
        )
        prompt = (
            f"DPN AI V5 MISSION {mission_id}\nObjective: {objective}\n"
            f"Goal contract: {self.cognitive.compact_context(contract)}\n"
            f"Current step: {step['title']}\nInstructions: {step['instructions']}\n"
            f"Required evidence: {json.dumps(step.get('evidence_required', []), ensure_ascii=False)}\n"
            f"Rollback plan: {step.get('rollback', '')}\n\n{context}\n\n"
            "Complete this step using tools where appropriate. Verify the result, provide exact paths, identify unresolved issues, and do not claim evidence you did not observe."
        )
        step_model = effective.get("model_routes", {}).get(step["role"], worker_model)
        response = await self.agent.run(
            conversation_id=conversation_id, user_message=prompt, model=step_model, think=selected_think,
            attachments=attachments if step["ordinal"] == 0 else [], profile=step["role"], project_id=project_id,
            source=f"mission:{mission_id}:{step['id']}",
        )
        result = {
            "message": response.message, "run_id": response.run_id, "profile": response.profile,
            "generated_files": response.generated_files, "tool_count": len(response.traces),
            "evidence_required": step.get("evidence_required", []),
        }
        return result, len(response.traces)

    async def run(self, objective: str, conversation_id: str | None = None, project_id: str | None = None,
                  attachments: list[str] | None = None, profile: str = "auto", model: str | None = None,
                  think: bool | str | None = None, budget: dict[str, Any] | None = None) -> dict[str, Any]:
        effective = self.agent.effective_settings()
        maximum_mode = str(effective.get("intelligence_mode") or "maximum") == "maximum"
        worker_request = model or ("__maximum__" if maximum_mode else (effective.get("worker_model") or effective["model"]))
        planner_request = effective.get("planner_model") or ("__maximum__" if maximum_mode else worker_request)
        reviewer_request = effective.get("reviewer_model") or ("__maximum__" if maximum_mode else worker_request)
        if hasattr(self.ollama, "select_best_model"):
            worker_model = await self.ollama.select_best_model(
                worker_request, profile=profile, intelligence_mode=str(effective.get("intelligence_mode") or "maximum"), fallback=str(effective["model"])
            )
            planner_model = await self.ollama.select_best_model(
                planner_request, profile="director", intelligence_mode=str(effective.get("intelligence_mode") or "maximum"), fallback=worker_model
            )
            reviewer_model = await self.ollama.select_best_model(
                reviewer_request, profile="security", intelligence_mode=str(effective.get("intelligence_mode") or "maximum"), fallback=worker_model
            )
        else:
            worker_model = worker_request
            planner_model = effective.get("planner_model") or worker_model
            reviewer_model = effective.get("reviewer_model") or worker_model
        if think is None and hasattr(self.agent, "_adaptive_think"):
            selected_think = self.agent._adaptive_think(effective["think_level"], objective, attachments, profile, 0)
        else:
            selected_think = effective["think_level"] if think is None else think
        budget = budget or {}
        max_steps = max(1, min(int(budget.get("max_steps", self.settings.max_mission_steps)), self.settings.max_mission_steps))
        max_total_tool_calls = max(1, min(int(budget.get("max_tool_calls", effective.get("max_tool_calls", 80) * max_steps)), 10000))
        max_seconds = max(30, min(int(budget.get("max_seconds", effective.get("max_run_seconds", 1800) * max_steps)), 86400))
        stop_on_failure = bool(budget.get("stop_on_failure", False))
        auto_repair = bool(budget.get("auto_repair", True))
        review_quorum = max(1, min(int(budget.get("review_quorum", getattr(self.settings, "review_quorum", 1))), 4))
        mission_started = time.monotonic()
        conversation_id = self.db.ensure_conversation(conversation_id, objective)
        mission = self.db.create_mission(
            objective, conversation_id, project_id, "mission",
            {"planner": planner_model, "worker": worker_model, "reviewer": reviewer_model},
            {**budget, "max_steps": max_steps, "max_tool_calls": max_total_tool_calls, "max_seconds": max_seconds,
             "stop_on_failure": stop_on_failure, "auto_repair": auto_repair, "review_quorum": review_quorum},
        )
        mission_id = mission["id"]
        contract = self.cognitive.derive_contract(objective)
        self.cognitive.save_contract(mission_id, contract)
        self.db.add_checkpoint(mission_id, "goal-contract-created", {"contract": contract.to_dict()})
        plan = await self.plan(contract, planner_model, selected_think, max_steps)
        step_ids: list[str] = []
        for index, raw in enumerate(plan.get("steps", [])):
            dependencies = [step_ids[dep] for dep in raw.get("dependencies", []) if isinstance(dep, int) and 0 <= dep < len(step_ids)]
            instructions = str(raw.get("instructions", "")) + "\n\nEvidence required: " + json.dumps(raw.get("evidence_required", []), ensure_ascii=False)
            step = self.db.add_mission_step(
                mission_id, index, str(raw.get("role", profile)), str(raw.get("title", f"Step {index + 1}")),
                instructions, dependencies,
            )
            # Preserve v5 execution controls in the step result before execution.
            self.db.update_mission_step(step["id"], result={
                "evidence_required": raw.get("evidence_required", []), "max_attempts": raw.get("max_attempts", 2),
                "rollback": raw.get("rollback", ""), "phase": "planned",
            })
            step_ids.append(step["id"])
        self.db.update_mission(mission_id, "running", {"plan": plan, "contract": contract.to_dict()})
        evidence: list[dict[str, Any]] = []
        failed = False
        total_tool_calls = 0
        for step in self.db.list_mission_steps(mission_id):
            planned = step.get("result") or {}
            step["evidence_required"] = planned.get("evidence_required", [])
            step["max_attempts"] = max(1, min(int(planned.get("max_attempts", 2)), 5))
            step["rollback"] = planned.get("rollback", "")
            if time.monotonic() - mission_started > max_seconds:
                self.db.update_mission_step(step["id"], "blocked", {"reason": "Mission runtime budget reached"})
                failed = True
                continue
            if total_tool_calls >= max_total_tool_calls:
                self.db.update_mission_step(step["id"], "blocked", {"reason": "Mission tool-call budget reached"})
                failed = True
                continue
            dependencies = [self.db.get_mission_step(dep) for dep in step.get("dependencies", [])]
            if any(not dep or dep.get("status") != "completed" for dep in dependencies):
                self.db.update_mission_step(step["id"], "blocked", {"reason": "Dependency did not complete"})
                failed = True
                continue
            last_error = None
            completed = False
            for attempt in range(1, step["max_attempts"] + 1):
                self.db.update_mission_step(step["id"], "running", increment_attempts=True)
                try:
                    result, tool_count = await self._execute_step(
                        mission_id, objective, contract, step, conversation_id, project_id, attachments,
                        selected_think, worker_model, effective,
                    )
                    total_tool_calls += tool_count
                    result["attempt"] = attempt
                    self.db.update_mission_step(step["id"], "completed", result)
                    self.db.add_checkpoint(mission_id, f"step-{step['ordinal']}-completed", result, step["id"])
                    evidence.append({"step": step["title"], **result})
                    completed = True
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = f"{type(exc).__name__}: {exc}"
                    self.db.add_checkpoint(mission_id, f"step-{step['ordinal']}-attempt-{attempt}-failed", {"error": last_error}, step["id"])
            if not completed:
                result = {"error": last_error or "Step failed", "rollback": step.get("rollback", "")}
                self.db.update_mission_step(step["id"], "failed", result)
                evidence.append({"step": step["title"], **result})
                failed = True
                if stop_on_failure:
                    break

        deterministic = self.cognitive.verify_evidence(evidence, contract)
        deterministic["evaluator"] = "deterministic"
        self.db.add_evaluation(mission_id, "deterministic", deterministic["verdict"], deterministic["confidence"], deterministic)

        if auto_repair and deterministic["verdict"] != "pass" and not stop_on_failure and total_tool_calls < max_total_tool_calls and time.monotonic() - mission_started < max_seconds:
            repair_prompt = (
                f"DPN AI mission {mission_id} did not pass deterministic verification.\n"
                f"Goal contract: {self.cognitive.compact_context(contract)}\n"
                f"Verification issues: {json.dumps(deterministic.get('issues', []), ensure_ascii=False)}\n"
                "Inspect the actual workspace and evidence. Repair only verified defects, run validation, and report exact evidence."
            )
            try:
                response = await self.agent.run(
                    conversation_id=conversation_id, user_message=repair_prompt, model=reviewer_model, think=selected_think,
                    attachments=[], profile="security", project_id=project_id, source=f"mission-repair:{mission_id}",
                )
                repair_result = {
                    "step": "Automatic verification repair", "message": response.message, "run_id": response.run_id,
                    "profile": response.profile, "generated_files": response.generated_files, "tool_count": len(response.traces),
                }
                total_tool_calls += len(response.traces)
                evidence.append(repair_result)
                self.db.add_checkpoint(mission_id, "automatic-repair-completed", repair_result)
                deterministic = self.cognitive.verify_evidence(evidence, contract)
                deterministic["evaluator"] = "deterministic"
                self.db.add_evaluation(mission_id, "deterministic-after-repair", deterministic["verdict"], deterministic["confidence"], deterministic)
            except Exception as exc:  # noqa: BLE001
                evidence.append({"step": "Automatic verification repair", "error": f"{type(exc).__name__}: {exc}"})

        reports: list[dict[str, Any]] = [deterministic]
        perspectives = ["security", "requirements", "operations", "adversarial"]
        for perspective in perspectives[:review_quorum]:
            report = await self.review(contract, evidence, reviewer_model, selected_think, perspective)
            reports.append(report)
            self.db.add_evaluation(mission_id, perspective, report["verdict"], float(report.get("confidence", 0.0)), report)
        review = self._consensus(reports)
        status = "failed" if review.get("verdict") == "fail" else "completed"
        result = {
            "plan": plan, "contract": contract.to_dict(), "evidence": evidence, "review": review,
            "checkpoints": self.db.list_checkpoints(mission_id), "evaluations": self.db.list_evaluations(mission_id),
            "usage": {
                "tool_calls": total_tool_calls, "elapsed_seconds": round(time.monotonic() - mission_started, 3),
                "budget": {"max_steps": max_steps, "max_tool_calls": max_total_tool_calls, "max_seconds": max_seconds,
                           "review_quorum": review_quorum, "auto_repair": auto_repair},
            },
        }
        self.db.update_mission(mission_id, status, result)
        summary = review.get("summary") or "Mission complete."
        self.db.add_message(conversation_id, "assistant", summary, {"mission_id": mission_id, "review": review, "source": "mission-summary"})
        return {
            "ok": status == "completed", "mission_id": mission_id, "conversation_id": conversation_id,
            "status": status, "contract": contract.to_dict(), "plan": plan, "evidence": evidence,
            "review": review, "message": summary,
        }