from __future__ import annotations

from typing import Any


LANGUAGE_PROFILES: dict[str, dict[str, Any]] = {
    "python": {"extensions": [".py"], "checks": ["pytest", "ruff", "mypy"], "runtime": "python"},
    "javascript": {"extensions": [".js", ".mjs", ".cjs"], "checks": ["npm test", "npm run lint"], "runtime": "node"},
    "typescript": {"extensions": [".ts", ".tsx"], "checks": ["npm test", "npm run lint", "npm run build"], "runtime": "node"},
    "lua": {"extensions": [".lua"], "checks": ["lua"], "runtime": "lua"},
    "rust": {"extensions": [".rs"], "checks": ["cargo test", "cargo check"], "runtime": "cargo"},
    "go": {"extensions": [".go"], "checks": ["go test ./..."], "runtime": "go"},
    "dotnet": {"extensions": [".cs", ".fs", ".vb"], "checks": ["dotnet test", "dotnet build"], "runtime": "dotnet"},
    "java": {"extensions": [".java"], "checks": ["javac"], "runtime": "java"},
}


def _normalize_languages(languages: list[str] | None) -> list[str]:
    aliases = {"py": "python", "js": "javascript", "ts": "typescript", "csharp": "dotnet", "c#": "dotnet"}
    result: list[str] = []
    for raw in languages or []:
        key = aliases.get(str(raw).strip().lower(), str(raw).strip().lower())
        if key in LANGUAGE_PROFILES and key not in result:
            result.append(key)
    return result


def build_coding_mission_plan(
    objective: str,
    project_path: str = ".",
    languages: list[str] | None = None,
    mode: str = "implement",
    max_repair_passes: int = 3,
    require_tests: bool = True,
    package_release: bool = False,
) -> dict[str, Any]:
    """Return a deterministic, repository-aware software mission plan.

    The plan is intentionally side-effect free. The runtime executes each phase
    through DPN AI's existing workspace, command, approval, and evidence gates.
    """
    normalized_mode = str(mode or "implement").strip().lower()
    if normalized_mode not in {"implement", "debug", "refactor", "review", "test", "release"}:
        normalized_mode = "implement"
    selected_languages = _normalize_languages(languages)
    repair_passes = max(0, min(int(max_repair_passes), 5))

    checks: list[str] = []
    for language in selected_languages:
        checks.extend(LANGUAGE_PROFILES[language]["checks"])
    checks = list(dict.fromkeys(checks))

    phases = [
        {
            "name": "inventory",
            "purpose": "Inspect the project tree, manifests, entry points, configuration, tests, and repository status before editing anything.",
            "tools": ["directory_tree", "list_files", "read_file", "search_text", "file_hash"],
            "evidence": ["project structure", "detected stack", "existing tests", "important entry points"],
        },
        {
            "name": "understand",
            "purpose": "Build an implementation map from existing architecture and trace the code paths relevant to the objective.",
            "tools": ["search_text", "read_file", "search_knowledge", "analyze_goal"],
            "evidence": ["affected components", "dependencies", "constraints", "acceptance criteria"],
        },
        {
            "name": "snapshot",
            "purpose": "Create a recoverable workspace checkpoint before broad modifications.",
            "tools": ["create_workspace_snapshot"],
            "evidence": ["snapshot identifier"],
        },
        {
            "name": "implement",
            "purpose": f"Perform the requested {normalized_mode} work using minimal, architecture-consistent edits.",
            "tools": ["read_file", "replace_text", "write_file", "make_directory", "copy_path"],
            "evidence": ["changed files", "reason for each change"],
        },
        {
            "name": "static_validation",
            "purpose": "Run syntax, lint, type, or build checks that are already available in the project environment.",
            "tools": ["run_command", "run_python_sandbox"],
            "suggested_checks": checks,
            "evidence": ["command", "exit code", "stdout/stderr summary"],
        },
        {
            "name": "test",
            "purpose": "Run relevant existing tests and add focused regression tests when the requested change requires them.",
            "tools": ["run_command", "read_file", "write_file", "replace_text"],
            "required": bool(require_tests),
            "evidence": ["tests executed", "pass/fail counts", "new regression coverage"],
        },
        {
            "name": "repair_loop",
            "purpose": "Diagnose validation failures, make the smallest justified repair, and rerun the failing checks.",
            "max_passes": repair_passes,
            "stop_conditions": ["all required checks pass", "repair budget exhausted", "missing dependency or external approval blocks progress"],
            "evidence": ["failure cause", "repair applied", "retest result"],
        },
        {
            "name": "review",
            "purpose": "Review the final diff for regressions, dead code, security issues, duplicated logic, and incomplete acceptance criteria.",
            "tools": ["directory_tree", "search_text", "read_file", "file_hash"],
            "evidence": ["review findings", "remaining limitations"],
        },
    ]
    if package_release or normalized_mode == "release":
        phases.append({
            "name": "package",
            "purpose": "Prepare a release-ready artifact only after required validation succeeds.",
            "tools": ["file_hash", "discover_tools"],
            "evidence": ["artifact path", "checksum", "release notes or manifest"],
        })
    phases.append({
        "name": "deliver",
        "purpose": "Return changed files, validation evidence, unresolved issues, and exact next actions without claiming unverified success.",
        "evidence": ["changed files", "test results", "known limitations"],
    })

    return {
        "ok": True,
        "objective": objective.strip(),
        "project_path": project_path or ".",
        "mode": normalized_mode,
        "languages": selected_languages,
        "recommended_checks": checks,
        "max_repair_passes": repair_passes,
        "require_tests": bool(require_tests),
        "package_release": bool(package_release or normalized_mode == "release"),
        "execution_policy": {
            "inspect_before_edit": True,
            "prefer_exact_edits_over_full_rewrites": True,
            "snapshot_before_broad_changes": True,
            "workspace_boundary_required": True,
            "do_not_install_dependencies_implicitly": True,
            "do_not_bypass_command_or_approval_gates": True,
            "do_not_claim_tests_passed_without_command_evidence": True,
            "repair_only_from_observed_failures": True,
            "preserve_existing_architecture_unless_refactor_is_requested": True,
        },
        "phases": phases,
    }


def register(registry):
    registry.register(
        name="plan_coding_mission",
        description=(
            "Plan an advanced whole-project coding mission for implementation, debugging, refactoring, testing, review, or release. "
            "The plan inspects architecture first, checkpoints state, performs focused multi-file edits, validates with available tooling, "
            "runs a bounded repair loop, and requires evidence before completion."
        ),
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "project_path": {"type": "string", "default": "."},
                "languages": {"type": "array", "items": {"type": "string"}, "default": []},
                "mode": {"type": "string", "enum": ["implement", "debug", "refactor", "review", "test", "release"], "default": "implement"},
                "max_repair_passes": {"type": "integer", "minimum": 0, "maximum": 5, "default": 3},
                "require_tests": {"type": "boolean", "default": True},
                "package_release": {"type": "boolean", "default": False},
            },
            "required": ["objective"],
            "additionalProperties": False,
        },
        function=build_coding_mission_plan,
        risk="read",
    )
