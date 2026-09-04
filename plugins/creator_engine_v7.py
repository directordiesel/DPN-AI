from __future__ import annotations

from typing import Any

_SUPPORTED_ARTIFACTS = {
    "document", "pdf", "spreadsheet", "presentation", "image", "chart", "audio", "video", "code", "bundle"
}


def build_creation_plan(
    objective: str,
    artifacts: list[dict[str, Any]] | None = None,
    brand: dict[str, Any] | None = None,
    max_artifacts: int = 20,
) -> dict[str, Any]:
    objective = str(objective or "").strip()
    if not objective:
        return {"ok": False, "error": "objective is required"}

    budget = max(1, min(int(max_artifacts), 50))
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(artifacts or []):
        kind = str(item.get("kind") or "document").strip().lower()
        if kind not in _SUPPORTED_ARTIFACTS:
            kind = "document"
        name = str(item.get("name") or f"artifact-{index + 1}").strip()
        key = f"{kind}:{name}"
        if key in seen or len(normalized) >= budget:
            continue
        seen.add(key)
        normalized.append({
            "kind": kind,
            "name": name,
            "purpose": str(item.get("purpose") or "").strip(),
            "depends_on": [str(v).strip() for v in item.get("depends_on", []) if str(v).strip()][:20],
            "verification": str(item.get("verification") or "structural").strip().lower(),
        })

    return {
        "ok": True,
        "engine": "dpn-creator-engine-v7",
        "objective": objective,
        "artifact_budget": budget,
        "artifacts": normalized,
        "brand": dict(brand or {}),
        "phases": [
            {"name": "brief", "purpose": "Resolve audience, format, constraints, source material, branding, and acceptance criteria."},
            {"name": "dependency_graph", "purpose": "Order artifacts so source content and data are created before dependent outputs."},
            {"name": "generate", "purpose": "Create each artifact with the native tool best suited to its format."},
            {"name": "inspect", "purpose": "Open or parse generated artifacts and verify they are structurally valid and complete."},
            {"name": "cross_check", "purpose": "Check consistency across related artifacts, versions, numbers, labels, branding, and filenames."},
            {"name": "package", "purpose": "Return usable files with provenance, validation evidence, and a clear artifact manifest."},
        ],
        "policy": {
            "native_format_generation": True,
            "source_grounding_required": True,
            "no_fake_validation": True,
            "open_and_inspect_outputs": True,
            "cross_artifact_consistency": True,
            "preserve_brand_constraints": True,
            "no_silent_overwrite": True,
            "explicit_failure_reporting": True,
        },
    }


def evaluate_creation_evidence(
    artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    checked: list[dict[str, Any]] = []
    ready = True
    for item in list(artifacts or [])[:100]:
        path = str(item.get("path") or "").strip()
        kind = str(item.get("kind") or "").strip().lower()
        exists = bool(item.get("exists"))
        inspected = bool(item.get("inspected"))
        valid = bool(item.get("valid"))
        evidence = item.get("evidence")
        passed = bool(path and kind in _SUPPORTED_ARTIFACTS and exists and inspected and valid and evidence)
        checked.append({
            "path": path,
            "kind": kind,
            "exists": exists,
            "inspected": inspected,
            "valid": valid,
            "evidence": evidence,
            "passed": passed,
        })
        if not passed:
            ready = False
    if not checked:
        ready = False

    return {
        "ok": True,
        "ready": ready,
        "artifacts": checked,
        "failed_or_unverified": [item["path"] or "unnamed" for item in checked if not item["passed"]],
        "policy": "Creator completion requires an existing, inspected, valid artifact plus explicit evidence for every requested output.",
    }


def register(registry):
    registry.register(
        name="plan_creation_v7",
        description="Plan a coordinated multi-artifact creation mission for documents, PDFs, spreadsheets, presentations, images, charts, media, code, and bundles.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "artifacts": {"type": "array", "items": {"type": "object"}, "default": []},
                "brand": {"type": "object", "default": {}},
                "max_artifacts": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20}
            },
            "required": ["objective"],
            "additionalProperties": False
        },
        function=build_creation_plan,
        risk="read",
    )
    registry.register(
        name="evaluate_creation_evidence_v7",
        description="Verify generated artifacts exist, were inspected, are valid, and include explicit evidence before claiming completion.",
        parameters={
            "type": "object",
            "properties": {
                "artifacts": {"type": "array", "items": {"type": "object"}, "default": []}
            },
            "additionalProperties": False
        },
        function=evaluate_creation_evidence,
        risk="read",
    )
