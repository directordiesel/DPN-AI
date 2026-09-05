from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP_GRADLE = ROOT / "mobile/android/app/build.gradle.kts"
PROPS = ROOT / "mobile/android/gradle.properties"
WORKFLOW = ROOT / ".github/workflows/android-mobile-validation.yml"
MANIFEST = ROOT / "mobile/android/app/src/main/AndroidManifest.xml"
DATA_EXTRACTION_RULES = ROOT / "mobile/android/app/src/main/res/xml/data_extraction_rules.xml"
BACKUP_RULES = ROOT / "mobile/android/app/src/main/res/xml/backup_rules.xml"


class MobileReleaseHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gradle = APP_GRADLE.read_text(encoding="utf-8")
        cls.props = PROPS.read_text(encoding="utf-8")
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.manifest = MANIFEST.read_text(encoding="utf-8")
        cls.data_extraction_rules = DATA_EXTRACTION_RULES.read_text(encoding="utf-8")
        cls.backup_rules = BACKUP_RULES.read_text(encoding="utf-8")

    def test_release_is_not_debuggable_and_is_shrunk(self):
        self.assertIn("isDebuggable = false", self.gradle)
        self.assertIn("isMinifyEnabled = true", self.gradle)
        self.assertIn("isShrinkResources = true", self.gradle)

    def test_release_signing_is_external_and_fail_closed(self):
        for key in (
            "DPN_MOBILE_KEYSTORE",
            "DPN_MOBILE_STORE_PASSWORD",
            "DPN_MOBILE_KEY_ALIAS",
            "DPN_MOBILE_KEY_PASSWORD",
        ):
            self.assertIn(key, self.gradle)
        self.assertIn("verifyReleaseReadiness", self.gradle)
        self.assertNotIn('storePassword = "', self.gradle)
        self.assertNotIn('keyPassword = "', self.gradle)

    def test_production_version_must_be_explicit(self):
        self.assertIn('"1.0.0-dev"', self.gradle)
        self.assertIn("DPN_MOBILE_VERSION_CODE", self.gradle)
        self.assertIn("DPN_MOBILE_VERSION_NAME", self.gradle)
        self.assertIn("production semantic version", self.gradle)

    def test_manifest_keeps_network_and_backup_boundaries(self):
        self.assertIn('android:usesCleartextTraffic="false"', self.manifest)
        self.assertIn('android:allowBackup="false"', self.manifest)
        self.assertIn('android:dataExtractionRules="@xml/data_extraction_rules"', self.manifest)
        self.assertIn('android:fullBackupContent="@xml/backup_rules"', self.manifest)
        for domain in ("root", "file", "database", "sharedpref", "external"):
            self.assertIn(f'<exclude domain="{domain}" path="." />', self.data_extraction_rules)
            self.assertIn(f'<exclude domain="{domain}" path="." />', self.backup_rules)
        self.assertIn("<cloud-backup", self.data_extraction_rules)
        self.assertIn("<device-transfer>", self.data_extraction_rules)

    def test_ci_builds_debug_and_lints_without_release_secrets(self):
        self.assertIn(":app:assembleDebug", self.workflow)
        self.assertIn(":app:lintDebug", self.workflow)
        self.assertIn("Potential signing secret material found", self.workflow)
        self.assertIn("test_mobile_*.py", self.workflow)

    def test_gradle_properties_contains_no_secret_values(self):
        self.assertIn("intentionally NOT stored here", self.props)
        self.assertNotIn("STORE_PASSWORD=", self.props)
        self.assertNotIn("KEY_PASSWORD=", self.props)


if __name__ == "__main__":
    unittest.main()
