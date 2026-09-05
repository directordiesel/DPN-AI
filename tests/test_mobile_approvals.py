from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MOBILE = ROOT / "mobile" / "android" / "app" / "src" / "main"
CLIENT = (MOBILE / "java" / "com" / "dpntechnology" / "dpnai" / "network" / "ApprovalApiClient.kt").read_text(encoding="utf-8")
ACTIVITY = (MOBILE / "java" / "com" / "dpntechnology" / "dpnai" / "ApprovalsActivity.kt").read_text(encoding="utf-8")
MAIN = (MOBILE / "java" / "com" / "dpntechnology" / "dpnai" / "MainActivity.kt").read_text(encoding="utf-8")
MANIFEST = (MOBILE / "AndroidManifest.xml").read_text(encoding="utf-8")


def test_mobile_approvals_reuse_unified_backend_boundary():
    assert '"/api/approvals$query"' in CLIENT
    assert '"/api/approvals/$safeId/decision"' in CLIENT
    assert 'require(path.startsWith("/api/approvals"))' in CLIENT
    assert "second AI" not in CLIENT.lower()


def test_mobile_approval_decisions_are_explicit_and_bounded():
    assert 'setOf("approved", "denied")' in CLIENT
    assert 'require(decision in ALLOWED_DECISIONS)' in CLIENT
    assert 'JSONObject().put("decision", decision)' in CLIENT
    assert "Approve" in ACTIVITY
    assert "Deny" in ACTIVITY


def test_mobile_approvals_require_secure_pairing_and_https_auth():
    assert 'loadDesktopCredential()' in CLIENT
    assert 'scheme.equals("https", true)' in CLIENT
    assert 'X-DPN-Token' in CLIENT
    assert 'X-DPN-Device-ID' in CLIENT
    assert 'instanceFollowRedirects = false' in CLIENT
    assert 'connectTimeout = 8_000' in CLIENT
    assert 'MAX_RESPONSE_CHARS' in CLIENT


def test_approval_activity_is_internal_and_pairing_gated():
    assert '<activity android:name=".ApprovalsActivity" android:exported="false" />' in MANIFEST
    assert 'loadDesktopCredential() == null' in ACTIVITY
    assert 'finish()' in ACTIVITY
    assert 'addCapability(root, "Approval Inbox", ApprovalsActivity::class.java)' in MAIN
    assert 'setCapabilityButtons(active)' in MAIN
    assert 'capabilityButtons.forEach { it.isEnabled = enabled }' in MAIN


def test_mobile_approval_inbox_has_no_background_autonomous_decision_service():
    combined = CLIENT + ACTIVITY + MANIFEST
    assert "WorkManager" not in combined
    assert "JobService" not in combined
    assert "ForegroundService" not in combined
    assert "AlarmManager" not in combined
