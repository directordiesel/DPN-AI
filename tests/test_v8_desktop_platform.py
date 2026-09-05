from pathlib import Path

import pytest

from desktop.platform import DesktopMode, DesktopPreflight, DesktopRuntimePolicy, ServiceEndpoint


def test_desktop_policy_defaults_to_loopback_and_security_controls():
    policy = DesktopRuntimePolicy()
    policy.validate()
    assert policy.endpoint.host == "127.0.0.1"
    assert policy.allow_remote is False
    assert policy.require_authentication is True
    assert policy.require_audit is True
    assert policy.require_update_integrity is True


def test_remote_access_requires_explicit_tls_endpoint():
    with pytest.raises(ValueError, match="requires TLS"):
        DesktopRuntimePolicy(
            allow_remote=True,
            endpoint=ServiceEndpoint(host="0.0.0.0", port=8765, tls=False),
        ).validate()

    DesktopRuntimePolicy(
        allow_remote=True,
        endpoint=ServiceEndpoint(host="0.0.0.0", port=8765, tls=True),
    ).validate()


def test_security_controls_cannot_be_disabled():
    for override in (
        {"require_authentication": False},
        {"require_audit": False},
        {"require_update_integrity": False},
    ):
        with pytest.raises(ValueError):
            DesktopRuntimePolicy(**override).validate()


def test_preflight_requires_core_runtime_files(tmp_path: Path):
    policy = DesktopRuntimePolicy(mode=DesktopMode.SAFE)
    result = DesktopPreflight(tmp_path, policy).run()
    assert result.ready is False
    assert "missing-file: VERSION" in result.blockers
    assert "missing-file: app/main.py" in result.blockers
    assert "missing-file: requirements.txt" in result.blockers


def test_preflight_accepts_valid_core_layout(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "VERSION").write_text("8.0.0-dev\n", encoding="utf-8")
    (tmp_path / "app" / "main.py").write_text("# runtime\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("# deps\n", encoding="utf-8")

    result = DesktopPreflight(tmp_path, DesktopRuntimePolicy()).run()
    assert result.ready is True
    assert result.blockers == ()


def test_preflight_rejects_required_path_escape(tmp_path: Path):
    result = DesktopPreflight(tmp_path, DesktopRuntimePolicy()).run(["../outside.txt"])
    assert result.ready is False
    assert "unsafe-required-path: ../outside.txt" in result.blockers
