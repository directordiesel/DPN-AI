from pathlib import Path

import pytest

from desktop.platform import DesktopMode, DesktopRuntimePolicy, ServiceEndpoint, ServiceState
from desktop.supervisor import DesktopServiceSupervisor, SupervisorConfig


class FakeProcess:
    def __init__(self, exit_code=None, pid=4242):
        self._exit_code = exit_code
        self.pid = pid
        self.signals = []
        self.terminated = False
        self.killed = False

    def poll(self):
        return self._exit_code

    def terminate(self):
        self.terminated = True
        self._exit_code = 0

    def kill(self):
        self.killed = True
        self._exit_code = -9

    def wait(self, timeout=None):
        return self._exit_code

    def send_signal(self, value):
        self.signals.append(value)
        self._exit_code = 0


def make_repo(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "VERSION").write_text("8.0.0-dev\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("# deps\n", encoding="utf-8")
    (tmp_path / "app" / "main.py").write_text("# app\n", encoding="utf-8")
    return tmp_path


def test_supervisor_builds_loopback_uvicorn_command(tmp_path: Path):
    root = make_repo(tmp_path)
    supervisor = DesktopServiceSupervisor(
        SupervisorConfig(repository_root=root, python_executable="python"),
        DesktopRuntimePolicy(endpoint=ServiceEndpoint(host="127.0.0.1", port=9000)),
        process_factory=lambda *a, **k: FakeProcess(),
        health_check=lambda: True,
    )
    command = supervisor.build_command()
    assert command[:4] == ["python", "-m", "uvicorn", "app.main:app"]
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == "9000"


def test_supervisor_environment_disables_browser(tmp_path: Path):
    supervisor = DesktopServiceSupervisor(
        SupervisorConfig(repository_root=make_repo(tmp_path)),
        DesktopRuntimePolicy(),
        process_factory=lambda *a, **k: FakeProcess(),
    )
    env = supervisor.build_environment()
    assert env["DPN_DESKTOP_SUPERVISED"] == "1"
    assert env["DPN_NO_BROWSER"] == "1"
    assert env["DPN_DESKTOP_ALLOW_REMOTE"] == "0"


def test_start_reaches_healthy_state(tmp_path: Path):
    created = {}

    def factory(*args, **kwargs):
        created.update(kwargs)
        return FakeProcess()

    supervisor = DesktopServiceSupervisor(
        SupervisorConfig(repository_root=make_repo(tmp_path)),
        DesktopRuntimePolicy(),
        process_factory=factory,
        health_check=lambda: True,
    )
    snapshot = supervisor.start()
    assert snapshot.state is ServiceState.HEALTHY
    assert snapshot.pid == 4242
    assert created["stdin"] is not None
    assert created["stdout"] is not None
    assert created["stderr"] is not None


def test_start_blocks_missing_runtime(tmp_path: Path):
    supervisor = DesktopServiceSupervisor(
        SupervisorConfig(repository_root=tmp_path),
        DesktopRuntimePolicy(),
        process_factory=lambda *a, **k: FakeProcess(),
        health_check=lambda: True,
    )
    with pytest.raises(RuntimeError, match="missing-file"):
        supervisor.start()
    assert supervisor.snapshot.state is ServiceState.FAILED


def test_restart_budget_is_bounded(tmp_path: Path):
    root = make_repo(tmp_path)
    supervisor = DesktopServiceSupervisor(
        SupervisorConfig(repository_root=root, max_restart_attempts=1),
        DesktopRuntimePolicy(),
        process_factory=lambda *a, **k: FakeProcess(exit_code=1),
        health_check=lambda: False,
    )
    supervisor._process = FakeProcess(exit_code=1)
    first = supervisor.ensure_healthy()
    assert first.state is ServiceState.FAILED
    second = supervisor.ensure_healthy()
    assert second.state is ServiceState.FAILED
    assert second.last_error == "restart budget exhausted"


def test_safe_mode_forces_local_only_and_no_remote(tmp_path: Path):
    supervisor = DesktopServiceSupervisor(
        SupervisorConfig(repository_root=make_repo(tmp_path)),
        DesktopRuntimePolicy(
            mode=DesktopMode.NORMAL,
            endpoint=ServiceEndpoint(),
            allow_remote=False,
            allow_cloud=True,
        ),
        process_factory=lambda *a, **k: FakeProcess(),
        health_check=lambda: True,
    )
    safe = supervisor.enter_safe_mode()
    assert safe.policy.mode is DesktopMode.SAFE
    assert safe.policy.allow_cloud is False
    assert safe.policy.allow_remote is False
    assert safe.policy.require_authentication is True
    assert safe.policy.require_audit is True
