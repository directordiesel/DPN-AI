from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = (ROOT / "packaging/windows/build-release-assets.ps1").read_text(encoding="utf-8")


def test_production_signing_certificate_must_be_currently_valid():
    assert "$Certificate.NotBefore -gt $Now" in BUILDER
    assert "$Certificate.NotAfter -le $Now" in BUILDER
    assert "Production signing certificate is not currently valid." in BUILDER


def test_production_signing_certificate_requires_code_signing_eku():
    assert '$CodeSigningOid = "1.3.6.1.5.5.7.3.3"' in BUILDER
    assert "$Certificate.EnhancedKeyUsageList" in BUILDER
    assert "$EnhancedKeyUsageOids -notcontains $CodeSigningOid" in BUILDER
    assert "Production signing certificate is not authorized for code signing." in BUILDER
