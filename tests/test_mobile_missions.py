from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "mobile/android/app/src/main/java/com/dpntechnology/dpnai/network/MissionApiClient.kt"
ACTIVITY = ROOT / "mobile/android/app/src/main/java/com/dpntechnology/dpnai/MissionsActivity.kt"
MAIN = ROOT / "mobile/android/app/src/main/java/com/dpntechnology/dpnai/MainActivity.kt"
MANIFEST = ROOT / "mobile/android/app/src/main/AndroidManifest.xml"


def test_missions_use_existing_unified_backend_contracts():
    text = CLIENT.read_text(encoding="utf-8")
    assert '"/api/missions$suffix"' in text
    assert '"/api/missions/$safeId"' in text
    assert 'request("POST", "/api/missions"' in text
    assert 'setRequestProperty("X-DPN-Token"' in text
    assert 'setRequestProperty("X-DPN-Device-ID"' in text
    assert 'baseUri.scheme.equals("https", true)' in text
    assert 'instanceFollowRedirects = false' in text


def test_mission_launch_payload_is_bounded_and_uses_shared_profiles():
    text = CLIENT.read_text(encoding="utf-8")
    assert 'cleanObjective.length <= 100_000' in text
    assert 'attachments.size <= MAX_ATTACHMENTS' in text
    assert 'mission attachment must be workspace-relative' in text
    assert 'require(profile in ALLOWED_PROFILES)' in text
    assert '.put("budget", JSONObject())' in text


def test_mission_launch_handles_orchestrator_mission_id_contract():
    text = CLIENT.read_text(encoding="utf-8")
    assert 'payload.optString("mission_id")' in text
    assert 'return getMission(missionId)' in text


def test_missions_console_is_pairing_gated_and_internal():
    main = MAIN.read_text(encoding="utf-8")
    manifest = MANIFEST.read_text(encoding="utf-8")
    assert 'addCapability(root, "Missions", MissionsActivity::class.java)' in main
    assert 'setCapabilityButtons(active)' in main
    assert 'capabilityButtons.forEach { it.isEnabled = enabled }' in main
    assert 'android:name=".MissionsActivity" android:exported="false"' in manifest


def test_mission_actions_are_explicit_and_not_background_automation():
    text = ACTIVITY.read_text(encoding="utf-8")
    assert "Launch Verified Mission" in text
    assert "Refresh Missions" in text
    assert "View Mission Details" in text
    assert "setOnClickListener { launchMission() }" in text
    assert "WorkManager" not in text
    assert "JobScheduler" not in text
    assert "startService(" not in text


def test_project_link_is_verified_before_mobile_mission_launch():
    text = ACTIVITY.read_text(encoding="utf-8")
    assert 'desktopClient.listProjects().any { it.id == projectId }' in text
    assert 'project ID was not found on the paired desktop' in text
