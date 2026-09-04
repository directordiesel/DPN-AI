from pathlib import Path
from types import SimpleNamespace

import pytest

from desktop.windows_integration import (
    CLASSES_ROOT,
    RUN_KEY,
    TrayState,
    WindowsIntegrationController,
    WindowsIntegrationError,
)


def test_windows_integration_requires_executable_path():
    with pytest.raises(ValueError, match=r"\.exe"):
        WindowsIntegrationController(Path("dpn-ai.py"))


def test_windows_integration_rejects_quote_in_path(tmp_path: Path):
    with pytest.raises(ValueError, match="quote"):
        WindowsIntegrationController(tmp_path / 'bad"name.exe')


def test_registry_roots_are_per_user_only():
    assert RUN_KEY.startswith("HKCU\\")
    assert CLASSES_ROOT.startswith("HKCU\\")
    assert "HKLM" not in RUN_KEY
    assert "HKLM" not in CLASSES_ROOT


def test_non_windows_registry_mutation_fails_closed(tmp_path: Path, monkeypatch):
    exe = tmp_path / "DPN-AI.exe"
    controller = WindowsIntegrationController(exe)
    monkeypatch.setattr("desktop.windows_integration.os.name", "posix")
    with pytest.raises(WindowsIntegrationError, match="only available on Windows"):
        controller.install_startup()


def test_context_menu_command_quotes_executable_and_selected_file(tmp_path: Path, monkeypatch):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    exe = tmp_path / "DPN AI" / "DPN-AI.exe"
    controller = WindowsIntegrationController(exe, runner=runner)
    monkeypatch.setattr("desktop.windows_integration.os.name", "nt")
    controller.install_context_menu()

    assert len(calls) == 3
    flattened = "\n".join(" ".join(call) for call in calls)
    assert "HKCU\\Software\\Classes" in flattened
    assert '"%1"' in flattened
    assert f'"{exe.resolve()}" --open-file' in flattened


def test_open_with_registration_is_scoped_to_application(tmp_path: Path, monkeypatch):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    exe = tmp_path / "DPN-AI.exe"
    controller = WindowsIntegrationController(exe, runner=runner)
    monkeypatch.setattr("desktop.windows_integration.os.name", "nt")
    controller.install_open_with()
    flattened = "\n".join(" ".join(call) for call in calls)
    assert "Applications\\DPN-AI.exe" in flattened
    assert "FriendlyAppName" in flattened
    assert "OpenWithList" not in flattened


def test_registry_errors_are_not_silently_ignored(tmp_path: Path, monkeypatch):
    def runner(command, **kwargs):
        return SimpleNamespace(returncode=5, stdout="", stderr="Access denied")

    controller = WindowsIntegrationController(tmp_path / "DPN-AI.exe", runner=runner)
    monkeypatch.setattr("desktop.windows_integration.os.name", "nt")
    with pytest.raises(WindowsIntegrationError, match="Access denied"):
        controller.install_startup()


def test_tray_state_reports_real_state_without_negative_counts():
    state = TrayState(service_online=True, pending_approvals=-2, active_missions=3, update_available=True)
    assert "Online" in state.tooltip()
    assert "Missions 3" in state.tooltip()
    assert "Approvals 0" in state.tooltip()
    assert state.notification_reasons() == ("update-available",)


def test_tray_state_surfaces_approval_notification():
    state = TrayState(pending_approvals=2)
    assert state.notification_reasons() == ("approval-required",)
