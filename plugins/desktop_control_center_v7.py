from __future__ import annotations

from typing import Any

PANELS = {
    "overview", "chat", "missions", "coding", "creator", "projects", "memory",
    "automations", "research", "connectors", "models", "approvals", "files",
    "runs", "security", "diagnostics", "settings"
}


def build_desktop_control_center_plan(
    objective: str,
    panels: list[str] | None = None,
    native_shell_target: str = "windows",
    require_local_runtime: bool = True,
    require_recovery_controls: bool = True,
) -> dict[str, Any]:
    selected: list[str] = []
    for item in panels or ["overview", "chat", "missions", "projects", "automations", "models", "approvals", "diagnostics"]:
        value = str(item or "").strip().lower()
        if value in PANELS and value not in selected:
            selected.append(value)
    if not selected:
        selected = ["overview"]
    shell = str(native_shell_target or "windows").strip().lower()
    if shell not in {"windows", "web", "hybrid"}:
        shell = "windows"
    return {
        "ok": bool(str(objective or "").strip()),
        "objective": str(objective or "").strip(),
        "native_shell_target": shell,
        "panels": selected,
        "desktop_contract": {
            "single_ai_runtime": True,
            "desktop_first_layout": True,
            "local_runtime_health": True,
            "streaming_activity": True,
            "persistent_workspace_layout": True,
            "keyboard_command_palette": True,
            "system_tray_ready": True,
            "native_notifications_ready": True,
            "multi_window_ready": True,
            "offline_state_visible": True,
            "approval_state_visible": True,
            "security_state_visible": True,
        },
        "stages": [
            {"id": "runtime_status", "goal": "Show local AI core, model/provider, database, connector, automation, and network health without inventing unavailable state."},
            {"id": "workspace", "goal": "Restore the user's project, conversation, panes, filters, and last active mission while preserving per-project scope."},
            {"id": "command_center", "goal": "Expose missions, agents, queues, approvals, automations, project intelligence, files, runs, and diagnostics from one desktop-first surface."},
            {"id": "activity_stream", "goal": "Stream mission steps, tool calls, evidence, retries, checkpoints, blockers, approvals, and verification results with timestamps."},
            {"id": "safe_actions", "goal": "Require explicit confirmation for destructive/high-risk desktop actions and keep read-only exploration frictionless."},
            {"id": "recovery", "goal": "Provide pause, resume, retry, cancel, checkpoint restore, diagnostic export, safe restart, and failed-run inspection controls."},
            {"id": "native_shell", "goal": "Keep the UI contract compatible with a Windows executable shell, tray integration, notifications, updater, and deep-link/file-open actions."},
            {"id": "verify", "goal": "Verify visible state against backend/runtime APIs and reject stale or fabricated dashboard status."},
        ],
        "quality_gates": [
            "visible_state_matches_runtime", "destructive_actions_require_approval", "offline_state_is_explicit",
            "mission_evidence_is_inspectable", "failed_runs_are_not_hidden", "recovery_controls_are_available",
            "project_scope_is_visible", "security_and_connector_state_is_visible", "desktop_shell_contract_is_versioned"
        ],
        "execution_policy": {
            "require_local_runtime": bool(require_local_runtime),
            "require_recovery_controls": bool(require_recovery_controls),
            "never_fake_online_or_model_status": True,
            "never_hide_failed_or_blocked_work": True,
            "never_auto_approve_protected_actions": True,
            "preserve_project_and_user_scope": True,
            "stream_progress_from_real_events": True,
            "surface_verification_evidence": True,
            "separate_stable_version_from_dev_channel": True,
            "support_keyboard_and_accessibility_navigation": True,
            "native_shell_must_not_spawn_terminal_for_normal_use": True,
        },
    }


def evaluate_control_center_state(state: dict[str, Any]) -> dict[str, Any]:
    required = ["runtime", "version", "project_scope", "mission_state", "approval_state", "verification_state"]
    missing = [key for key in required if state.get(key) in (None, "", {})]
    inconsistencies = list(state.get("inconsistencies") or [])
    blocked = bool(state.get("blocked"))
    return {
        "ok": not missing and not inconsistencies and not blocked,
        "missing_state": missing,
        "inconsistencies": inconsistencies,
        "blocked": blocked,
        "completion_allowed": not missing and not inconsistencies and not blocked,
    }


def register(registry) -> None:
    registry.register(
        name="plan_desktop_control_center_v7",
        description="Plan the DPN AI v7 desktop-first control center and native Windows shell contract with real runtime state, approvals, recovery, projects, missions, models, connectors, security, and verification evidence.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "panels": {"type": "array", "items": {"type": "string"}},
                "native_shell_target": {"type": "string", "enum": ["windows", "web", "hybrid"], "default": "windows"},
                "require_local_runtime": {"type": "boolean", "default": True},
                "require_recovery_controls": {"type": "boolean", "default": True}
            },
            "required": ["objective"],
            "additionalProperties": False
        },
        function=build_desktop_control_center_plan,
        risk="read"
    )
    registry.register(
        name="evaluate_desktop_control_center_state_v7",
        description="Evaluate whether desktop-control-center state is complete and consistent with runtime evidence.",
        parameters={"type": "object", "properties": {"state": {"type": "object"}}, "required": ["state"]},
        function=evaluate_control_center_state,
        risk="read"
    )
