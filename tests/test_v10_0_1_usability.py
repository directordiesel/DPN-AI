from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
ANDROID_MAIN = ROOT / "mobile" / "android" / "app" / "src" / "main"

BROKEN_ENCODING_MARKERS = {
    "â": "UTF-8 text decoded as a legacy single-byte encoding",
    "Ã": "UTF-8 multibyte text decoded incorrectly",
    "\ufffd": "Unicode replacement character",
}


def _user_facing_sources() -> list[Path]:
    paths = []
    for pattern in ("*.html", "*.js", "*.css"):
        paths.extend(STATIC.glob(pattern))
    if ANDROID_MAIN.exists():
        paths.extend(ANDROID_MAIN.rglob("*.kt"))
        paths.extend(ANDROID_MAIN.rglob("*.xml"))
    return sorted(path for path in paths if path.is_file())


def test_user_facing_sources_contain_no_known_mojibake_markers():
    failures = []
    for path in _user_facing_sources():
        text = path.read_text(encoding="utf-8")
        for marker, meaning in BROKEN_ENCODING_MARKERS.items():
            if marker in text:
                failures.append(f"{path.relative_to(ROOT)} contains {marker!r}: {meaning}")
    assert not failures, "\n".join(failures)


def test_live_activity_overlay_is_fully_removed_not_merely_collapsed():
    js = (STATIC / "v9-desktop.js").read_text(encoding="utf-8")
    css = (STATIC / "v9-desktop.css").read_text(encoding="utf-8")

    for token in (
        "v9ActivityRail",
        "v9ActivityToggle",
        "v9ActivityState",
        "v9MissionCount",
        "v9ApprovalCount",
        "v9AutomationCount",
        "v9ConnectorCount",
        "LIVE ACTIVITY",
        "mirrorDesktopSummary",
    ):
        assert token not in js

    assert ".v9-activity-rail" not in css
    assert ".v9-activity-grid" not in css
    assert ".v9-activity-rail.collapsed" not in css


def test_main_dashboard_status_cards_remain_after_overlay_removal():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for element_id in (
        "desktopCoreCard",
        "desktopMissionCard",
        "desktopApprovalCard",
        "desktopModelCard",
        "desktopAutomationCard",
        "desktopConnectorCard",
    ):
        assert f'id="{element_id}"' in html


def test_activity_overlay_cleanup_does_not_leave_orphaned_focus_ui():
    js = (STATIC / "v9-desktop.js").read_text(encoding="utf-8")
    css = (STATIC / "v9-desktop.css").read_text(encoding="utf-8")

    assert "v9FocusDrawer" not in js
    assert "v9FocusClose" not in js
    assert ".v9-focus-drawer" not in css
    assert ".v9-focus-grid" not in css


def test_settings_are_grouped_and_explained_in_plain_language():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for section in (
        "General",
        "AI Models",
        "Permissions & Safety",
        "Web & Browser",
        "Voice & Media",
        "Automations",
        "Connectors",
        "Files & Workspace",
        "Advanced",
    ):
        assert "title:'" + section + "'" in js

    assert "Configure DPN AI without guessing" in js
    assert "Load Recommended Settings" in js
    assert "Tool Server Connections" in js
    assert "using the MCP standard" in js
    assert "Search and memory matching model" in js
    assert "High risk" in js


def test_normal_settings_do_not_require_raw_model_route_json():
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    assert 'id="settingModelRoutes"' not in js
    assert "JSON.parse($('settingModelRoutes')" not in js
    assert "data-model-route-row" in js
    assert "data-route-profile" in js
    assert "data-route-model" in js
    assert "addModelRouteBtn" in js
    assert "collectSettingsModelRoutes" in js
    assert "A work profile can only have one preferred model" in js


def test_sidebar_uses_plain_labels_instead_of_decorative_glyph_prefixes():
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert "WINDOWS DESKTOP PLATFORM v8" not in html
    assert "DPN AI DESKTOP PLATFORM" in html
    assert "MCP Tool Bridge" not in html
    assert ">Tool Server Connections</button>" in html
    assert "Tool Server Connections (MCP)" not in html

    for glyph in ("◉", "▰", "⬢", "▧", "✧", "⇌", "⚠", "◆", "◷", "⌁", "⬡", "▣", "◈", "✦", "⇄"):
        assert glyph not in html


def test_primary_modules_explain_purpose_first_action_and_safety():
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "function moduleIntro(title, purpose, firstAction, safety = '')" in js
    assert "What is this?" in js
    assert "Start here:" in js
    assert "Safety:" in js

    for module in (
        "Voice Command Center",
        "Workspace Files",
        "Local Memory",
        "Projects & Task Board",
        "Local Automations",
        "Runs & Audit Trail",
        "Workspace Snapshots",
        "System Diagnostics",
        "Universal Missions",
        "Autonomous Job Queue",
        "Knowledge Graph",
        "Sandbox Lab",
        "Capability Forge",
        "Tool Server Connections",
        "Approval Inbox",
        "Skills & Workflows",
        "Connectors & Secrets",
    ):
        assert "moduleIntro('" + module + "'" in js


def test_destructive_memory_delete_requires_confirmation():
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "Delete this saved memory?" in js
    delete_call = "api(`/api/memories/${button.dataset.memory}`, {method:'DELETE'})"
    assert delete_call in js
    assert js.index("Delete this saved memory?") < js.index(delete_call)



def test_desktop_shell_source_uses_plain_ascii_ui_copy():
    for name in ("index.html", "app.js", "v8-desktop.js", "v9-desktop.js"):
        text = (STATIC / name).read_text(encoding="utf-8")
        non_ascii = sorted({char for char in text if ord(char) > 127})
        assert not non_ascii, f"{name} contains non-ASCII UI characters: {non_ascii}"

    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert ">Menu</button>" in html
    assert ">Reindex</button>" in html
    assert ">Stop</button>" in html
    assert ">Voice Settings</button>" in html
    assert ">Send</button>" in html
    assert ">Close</button>" in html

    v9 = (STATIC / "v9-desktop.js").read_text(encoding="utf-8")
    assert ">Commands</button>" in v9


def test_literal_dom_references_resolve_and_static_ids_are_unique():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    scripts = "\n".join(
        (STATIC / name).read_text(encoding="utf-8")
        for name in ("app.js", "v8-desktop.js", "v9-desktop.js")
    )
    markup = html + "\n" + scripts

    declared = set(re.findall(r'\bid=["\']([^"\'$}{]+)["\']', markup))
    references = set(re.findall(r"\$\(['\"]([^'\"]+)['\"]\)", scripts))
    references.update(re.findall(r"getElementById\(['\"]([^'\"]+)['\"]\)", scripts))

    assert references - declared == set()

    static_ids = re.findall(r'\bid=["\']([^"\']+)["\']', html)
    duplicates = sorted({item for item in static_ids if static_ids.count(item) > 1})
    assert duplicates == []


def test_every_static_button_with_an_id_is_wired_in_desktop_javascript():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    scripts = "\n".join(
        (STATIC / name).read_text(encoding="utf-8")
        for name in ("app.js", "v8-desktop.js", "v9-desktop.js")
    )
    button_ids = re.findall(r'<button\b[^>]*\bid="([^"]+)"', html)
    missing = [button_id for button_id in button_ids if button_id not in scripts]
    assert missing == []


def test_modal_supports_scrolling_semantics_escape_focus_trap_and_focus_restore():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'aria-labelledby="modalTitle"' in html
    assert 'id="modalBackdrop" aria-hidden="true"' in html

    assert "let modalReturnFocus = null" in js
    assert "function modalIsOpen()" in js
    assert "function modalFocusableElements()" in js
    assert "function trapModalFocus(event)" in js
    assert "event.key === 'Tab' && modalIsOpen()" in js
    assert "els.modalBackdrop.setAttribute('aria-hidden', 'false')" in js
    assert "els.modalBackdrop.setAttribute('aria-hidden', 'true')" in js
    assert "document.contains(target)" in js
    assert "target.focus({preventScroll:true})" in js
    assert "if (modalIsOpen()) { event.preventDefault(); closeModal(); return; }" in js

    assert ".modal-body {" in css
    assert "overflow: auto;" in css
    assert "max-height: calc(var(--dpn-viewport-height) - 28px);" in css


def test_user_visible_desktop_copy_has_no_stale_v5_labels():
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "v5.0.7 clarity engine" not in js
    assert "DPN AI v5 sandbox ready" not in js
    assert "Legacy model active:" not in js
    assert "DPN AI sandbox ready" in js
    assert "The local voice engine uses the highest-quality installed voice model" in js


def test_all_delete_requests_have_human_confirmation_nearby():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    lines = js.splitlines()
    delete_lines = [index for index, line in enumerate(lines) if "method:'DELETE'" in line or 'method:"DELETE"' in line]
    assert delete_lines
    unconfirmed = []
    for index in delete_lines:
        nearby = "\n".join(lines[max(0, index - 3): index + 1])
        if "confirm(" not in nearby:
            unconfirmed.append(index + 1)
    assert unconfirmed == []



def test_interface_shell_validator_covers_primary_controls_and_cache_is_rotated():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")

    required_ids = (
        "sidebar", "chat", "messages", "promptInput", "sendBtn", "modalBackdrop", "modal", "modalTitle", "modalBody",
        "newChatBtn", "refreshChatsBtn", "voiceBtn", "missionsBtn", "jobsBtn", "graphBtn", "sandboxBtn",
        "capabilityForgeBtn", "mcpBtn", "approvalsBtn", "projectsBtn", "automationsBtn", "runsBtn", "snapshotsBtn",
        "filesBtn", "memoryBtn", "skillsBtn", "connectorsBtn", "diagnosticsBtn", "settingsBtn", "menuBtn", "indexBtn",
        "micBtn", "stopVoiceBtn", "voiceSettingsBtn",
    )
    for element_id in required_ids:
        assert f"'{element_id}'" in js

    assert "DPN AI interface cache mismatch" in js
    assert "Repair cached interface" in js
    assert "dpn-ai-v10.0.1-ui-shell" in sw
    assert "dpn-ai-v10.0.0-ui-shell" not in sw
    assert "development-ui-shell" not in sw



def test_workspace_shortcuts_are_truthful_and_chat_preserves_context():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    desktop_js = (STATIC / "v8-desktop.js").read_text(encoding="utf-8")

    assert 'data-workspace="creator">Capability Forge</button>' in html
    assert 'data-workspace="research">Tool Servers</button>' in html
    assert 'data-workspace="creator">Creator Studio</button>' not in html
    assert 'data-workspace="research">Research & Tools</button>' not in html

    assert "chat: 'newChatBtn'" not in desktop_js
    assert "tab.dataset.workspace === 'chat'" in desktop_js
    assert "invokeExisting('closeModalBtn')" in desktop_js
    assert "document.getElementById('promptInput')?.focus()" in desktop_js
    assert "creator: 'capabilityForgeBtn'" in desktop_js
    assert "research: 'mcpBtn'" in desktop_js



def test_errors_are_actionable_bounded_and_redacted():
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "function userSafeErrorDetail(error)" in js
    assert "function showActionError(action, error, nextStep" in js
    assert "detail.length > 260" in js
    assert "[redacted]" in js
    assert "Bearer [redacted]" in js
    assert "Check DPN Core status and try again." in js
    assert "Opening Workspace Files" in js
    assert "Opening System Settings" in js
    assert "Starting voice input" in js
    assert "Uploading the file" in js
    assert "Running the operation" in js

    raw_backend_toasts = [
        line for line in js.splitlines()
        if "toast(error.message" in line
    ]
    assert raw_backend_toasts == [
        next(line for line in js.splitlines() if "collectSettingsModelRoutes()" in line and "toast(error.message" in line)
    ]


def test_empty_states_explain_a_next_action():
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    expected_guidance = (
        "Upload a file in Chat or add files to the configured workspace, then choose Reindex.",
        "Add a clearly named preference, fact, or decision above",
        "Enter a project name, describe the goal and constraints, then choose Create Project.",
        "Complete the schedule and operation form above",
        "Send a chat request, run a mission, or start an automation",
        "Create one before major edits, upgrades, or autonomous coding work",
        "Select Mission mode in Chat and send a complex goal",
        "Enter a complete goal above, choose Chat or Mission work",
        "Search for an existing subject, or add a sourced fact",
        "Add a small local capability above, validate it",
        "Add a trusted server above, discover its tools",
        "Protected actions will appear here automatically",
        "DPN AI can still operate normally",
        "Create one through an approved workflow-building operation",
        "Approved service connections will appear here",
    )
    for guidance in expected_guidance:
        assert guidance in js

    for vague_markup in (
        '<div class="empty-state">Workspace is empty.</div>',
        '<div class="empty-state">No durable memories saved.</div>',
        '<div class="empty-state">No local automations configured.</div>',
        '<div class="empty-state">No operation runs yet.</div>',
        '<div class="empty-state">No snapshots yet.</div>',
        '<div class="empty-state">No background jobs yet.</div>',
        '<div class="empty-state">No MCP servers configured.</div>',
        '<div class="empty-state">No actions are awaiting approval.</div>',
        '<div class="empty-state">No workflows created. The API and agent tools can create them.</div>',
        '<div class="empty-state">No connectors configured.</div>',
    ):
        assert vague_markup not in js


def test_raw_json_is_labeled_as_technical_evidence_where_user_facing():
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "Technical goal contract" in js
    assert "Technical step evidence" in js
    assert "Mission checkpoint evidence" in js
    assert "Independent evaluation evidence" in js
    assert "Consensus review evidence" in js
    assert "Technical plugin error details" in js
    assert "Technical validation evidence" in js
    assert "Exact action details - review before deciding" in js
    assert "<details open><summary>Goal contract</summary>" not in js


def test_unavailable_capabilities_explain_recovery_in_plain_language():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    desktop = (STATIC / "v8-desktop.js").read_text(encoding="utf-8")
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    for guidance in (
        "AI model service unavailable",
        "Start the configured AI model service, or open Settings > AI Models",
        "No AI model available - check AI Models settings",
        "NEEDS SETUP",
        "INSTALL REQUIRED",
        "DOCKER NEEDED",
        "install/start Docker or explicitly enable Direct host fallback in Settings",
        "Tool server support is not installed in this DPN AI environment",
        "install the optional MCP support dependencies and restart DPN AI",
    ):
        assert guidance in js

    assert "Model Gateway Offline" not in js
    assert "Model gateway offline" not in js
    assert "Add Disabled-by-Allowlist Server" not in js
    assert "MCP server configured with an empty allowlist." not in js
    assert "Save Allowlist" not in js
    assert "Desktop API is not responding" not in desktop
    assert "DPN Core not responding" in desktop
    assert "Make sure DPN AI is running. Status will reconnect automatically." in desktop
    assert "Waiting for mission summary API" not in html
    assert "Waiting for live mission status" in html


def test_advanced_terms_are_secondary_to_plain_language_labels():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert ">Tool Server Connections</button>" in html
    assert "Tool Server Connections (MCP)" not in html
    assert "Tool server support (MCP)" in js
    assert "using the MCP standard" in js
    assert "Local speech output" in js
    assert "Recognition model" in js
    assert "Neural TTS engine" not in js
    assert "STT model" not in js
    assert "Direct host fallback when Docker is unavailable" in js
    assert "This specialized model converts text into numeric meaning representations" in js


def test_structured_result_failures_use_safe_action_error_presenter():
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "Promoting the capability" in js
    assert "Restoring the plugin backup" in js
    assert "Discovering tool server capabilities" in js
    assert "Running the workflow" in js

    structured_error_ref = re.compile(r"(?<![A-Za-z0-9_])(?:r|result)\.error\b")
    unsafe_structured_errors = [
        line for line in js.splitlines()
        if structured_error_ref.search(line)
        and "showActionError" not in line
        and "userSafeErrorDetail" not in line
    ]
    assert unsafe_structured_errors == []


def test_expert_evidence_is_human_first_and_explicitly_labeled():
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "Technical tool evidence -" in js
    assert "Technical failure details" in js
    assert "Technical result and request payload" in js
    assert "Technical relationship data (JSON)" in js
    assert "function formatSandboxResult(result = {})" in js
    assert "Execution completed successfully." in js
    assert "Program output:" in js
    assert "Technical execution evidence:" in js
    assert "output.textContent=formatSandboxResult(r)" in js
    assert "output.textContent=JSON.stringify(r,null,2)" not in js



def test_active_windows_surfaces_use_current_version_source():
    active_bat_files = (
        "run_dpn_ai.bat",
        "repair_windows.bat",
        "doctor_windows.bat",
        "install_windows.bat",
        "install_core_only_windows.bat",
        "install_sentinel_hd_windows.bat",
    )
    for name in active_bat_files:
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "v5.0.7" not in text
        assert 'set "DPN_VERSION=unknown"' in text
        assert 'set /p DPN_VERSION=<"VERSION"' in text
        assert "v%DPN_VERSION%" in text

    installer = (ROOT / "INSTALL_DPN_AI.ps1").read_text(encoding="utf-8")
    assert "v5.0.7" not in installer
    assert "$DpnVersion" in installer
    assert "$VersionPath = Join-Path $Root 'VERSION'" in installer
    assert "'VERSION'" in installer

    issue_template = (ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").read_text(encoding="utf-8")
    assert 'placeholder: "v5.0.7"' not in issue_template
    assert "Version shown in DPN AI" in issue_template
