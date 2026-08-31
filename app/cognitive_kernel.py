from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from app.db import Database


TASK_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("software", ("code", "script", "app", "api", "debug", "server", "website", "database", "program")),
    ("fivem", ("fivem", "qbcore", "qbox", "lua", "fxmanifest", "onesync")),
    ("documents", ("document", "pdf", "word", "spreadsheet", "excel", "powerpoint", "presentation", "report")),
    ("media", ("image", "video", "audio", "voice", "photo", "render", "movie", "music")),
    ("research", ("research", "latest", "compare", "verify", "source", "evidence", "news")),
    ("business", ("business", "revenue", "customer", "sales", "pricing", "proposal", "marketing", "roi")),
    ("automation", ("automate", "workflow", "schedule", "webhook", "integration", "connector", "mcp")),
    ("desktop", ("computer", "screen", "desktop", "click", "type", "browser", "website")),
]


@dataclass(frozen=True)
class GoalContract:
    objective: str
    task_classes: list[str]
    required_capabilities: list[str]
    deliverables: list[str]
    success_criteria: list[str]
    constraints: list[str]
    risks: list[str]
    unknowns: list[str]
    confidence: float
    requires_current_information: bool
    requires_external_side_effects: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CognitiveKernel:
    """Deterministic reasoning guardrails around model-generated plans.

    This class does not attempt to replace the model. It turns an open-ended
    objective into an explicit contract, validates plans, tracks uncertainty,
    and performs artifact/evidence checks that do not depend on model claims.
    """

    def __init__(self, db: Database, workspace: Path):
        self.db = db
        self.workspace = workspace.resolve()

    @staticmethod
    def _sentences(text: str) -> list[str]:
        return [part.strip(" \n\t.-") for part in re.split(r"[\n.;]+", text) if part.strip()]

    def derive_contract(self, objective: str, constraints: list[str] | None = None) -> GoalContract:
        lower = objective.lower()
        classes: list[str] = []
        for task_class, keywords in TASK_PATTERNS:
            if any(keyword in lower for keyword in keywords):
                classes.append(task_class)
        if not classes:
            classes = ["general"]

        capabilities: list[str] = []
        mapping = {
            "software": ["workspace", "code_execution", "testing"],
            "fivem": ["workspace", "code_execution", "database_reasoning"],
            "documents": ["document_generation", "workspace"],
            "media": ["multimodal", "media_processing"],
            "research": ["web_research", "source_verification"],
            "business": ["planning", "document_generation"],
            "automation": ["workflows", "connectors"],
            "desktop": ["screen_understanding", "computer_control"],
            "general": ["planning", "workspace"],
        }
        for task_class in classes:
            capabilities.extend(mapping.get(task_class, []))
        capabilities = list(dict.fromkeys(capabilities))

        deliverables: list[str] = []
        extension_map = {
            ".pdf": "PDF file", ".docx": "Word document", ".xlsx": "Excel workbook",
            ".pptx": "PowerPoint presentation", ".zip": "release archive", ".py": "Python source",
            ".lua": "Lua source", ".js": "JavaScript source", ".ts": "TypeScript source",
        }
        for extension, label in extension_map.items():
            if extension in lower:
                deliverables.append(label)
        if any(word in lower for word in ("build", "create", "make", "generate", "develop")):
            deliverables.append("requested working output")
        if any(word in lower for word in ("test", "verify", "working", "production", "release")):
            deliverables.append("validation evidence")
        if not deliverables:
            deliverables = ["complete answer or usable artifact"]
        deliverables = list(dict.fromkeys(deliverables))

        success = [
            "The requested output exists and matches the objective.",
            "Claims of completion are supported by observable evidence.",
            "Known limitations and unverified assumptions are disclosed.",
        ]
        if "software" in classes or "fivem" in classes:
            success.extend(["Available tests or syntax checks pass.", "Configuration and startup instructions are included."])
        if "documents" in classes:
            success.append("Generated files open successfully and contain complete sections.")
        if "research" in classes:
            success.append("Time-sensitive claims use current, attributable sources.")
        if "desktop" in classes:
            success.append("External side effects are approval-controlled and recorded.")

        identified_constraints = list(constraints or [])
        if "standalone" in lower or "local" in lower or "offline" in lower:
            identified_constraints.append("Prefer local execution and local data storage.")
        if "no cloud" in lower:
            identified_constraints.append("Do not require cloud services.")
        identified_constraints = list(dict.fromkeys(identified_constraints))

        risks: list[str] = []
        external = any(word in lower for word in ("send", "post", "publish", "buy", "delete", "install", "click", "login", "email"))
        current = any(word in lower for word in ("latest", "current", "today", "news", "price", "weather", "schedule"))
        if external:
            risks.append("The request may cause external or destructive side effects.")
        if "desktop" in classes:
            risks.append("Computer-control actions can affect applications outside the workspace.")
        if "software" in classes or "fivem" in classes:
            risks.append("Generated code may require environment-specific integration testing.")
        if current:
            risks.append("The answer can become stale and requires current information.")

        unknowns: list[str] = []
        if len(objective.strip()) < 40:
            unknowns.append("The objective is brief; implicit requirements may be missing.")
        if "anything" in lower or "everything" in lower:
            unknowns.append("The objective is open-ended and must be bounded by a concrete success contract.")
        confidence = max(0.45, min(0.95, 0.55 + 0.05 * len(classes) + 0.03 * len(deliverables) - 0.08 * len(unknowns)))

        return GoalContract(
            objective=objective.strip(), task_classes=classes, required_capabilities=capabilities,
            deliverables=deliverables, success_criteria=list(dict.fromkeys(success)),
            constraints=identified_constraints, risks=risks, unknowns=unknowns,
            confidence=round(confidence, 2), requires_current_information=current,
            requires_external_side_effects=external,
        )

    def normalize_plan(self, plan: dict[str, Any], contract: GoalContract, max_steps: int) -> dict[str, Any]:
        raw_steps = plan.get("steps") if isinstance(plan, dict) else None
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError("Plan has no executable steps")
        steps: list[dict[str, Any]] = []
        valid_roles = {"director", "software", "fivem", "research", "business", "documents", "media", "automation", "security", "computer", "data", "science", "creative"}
        for index, raw in enumerate(raw_steps[:max_steps]):
            if not isinstance(raw, dict):
                continue
            role = str(raw.get("role") or "director")
            if role not in valid_roles:
                role = "director"
            dependencies = []
            for dep in raw.get("dependencies", []):
                if isinstance(dep, int) and 0 <= dep < index:
                    dependencies.append(dep)
            evidence = raw.get("evidence_required")
            if not isinstance(evidence, list) or not evidence:
                evidence = ["concrete result", "limitations"]
            steps.append({
                "title": str(raw.get("title") or f"Step {index + 1}")[:240],
                "role": role,
                "instructions": str(raw.get("instructions") or contract.objective)[:30_000],
                "dependencies": list(dict.fromkeys(dependencies)),
                "evidence_required": [str(item)[:300] for item in evidence[:10]],
                "max_attempts": max(1, min(int(raw.get("max_attempts", 2)), 5)),
                "rollback": str(raw.get("rollback") or "Restore the latest workspace snapshot or revert the exact changed files.")[:2000],
            })
        if not steps:
            raise ValueError("Plan contained no valid steps")
        return {
            "summary": str(plan.get("summary") or "Execute the goal contract with evidence and recovery controls."),
            "contract": contract.to_dict(),
            "steps": steps,
            "success_criteria": plan.get("success_criteria") or contract.success_criteria,
        }

    def verify_evidence(self, evidence: list[dict[str, Any]], contract: GoalContract) -> dict[str, Any]:
        files: list[dict[str, Any]] = []
        errors: list[str] = []
        completed_steps = 0
        tool_calls = 0
        for item in evidence:
            if item.get("error"):
                errors.append(str(item["error"])[:1000])
            else:
                completed_steps += 1
            tool_calls += int(item.get("tool_count") or 0)
            for path_value in item.get("generated_files") or []:
                try:
                    target = (self.workspace / str(path_value)).resolve()
                    target.relative_to(self.workspace)
                    exists = target.is_file()
                    files.append({
                        "path": str(path_value), "exists": exists,
                        "size_bytes": target.stat().st_size if exists else 0,
                    })
                    if not exists:
                        errors.append(f"Generated file is missing: {path_value}")
                    elif target.stat().st_size == 0:
                        errors.append(f"Generated file is empty: {path_value}")
                except Exception:
                    errors.append(f"Invalid generated path: {path_value}")
        required_artifact = any("output" in item.lower() or "file" in item.lower() or "artifact" in item.lower() for item in contract.deliverables)
        if required_artifact and not files and any(item in contract.task_classes for item in ("software", "documents", "media", "fivem")):
            errors.append("No generated artifact path was reported for an artifact-producing task.")
        score = 1.0
        if errors:
            score -= min(0.85, 0.22 * len(errors))
        if any("missing" in item.lower() or "empty" in item.lower() or "invalid generated path" in item.lower() for item in errors):
            score = min(score, 0.65)
        if completed_steps == 0:
            score = 0.0
        return {
            "verdict": "pass" if score >= 0.8 else "partial" if score >= 0.35 else "fail",
            "confidence": round(max(0.0, min(1.0, score)), 2),
            "completed_steps": completed_steps,
            "tool_calls": tool_calls,
            "files": files,
            "issues": errors,
            "criteria": contract.success_criteria,
        }

    def save_contract(self, mission_id: str, contract: GoalContract) -> dict[str, Any]:
        return self.db.upsert_goal_contract(mission_id, contract.to_dict())

    @staticmethod
    def compact_context(contract: GoalContract, max_chars: int = 12_000) -> str:
        text = json.dumps(contract.to_dict(), ensure_ascii=False, indent=2)
        return text[:max_chars]