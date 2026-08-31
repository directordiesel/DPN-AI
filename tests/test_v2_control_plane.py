import asyncio
from pathlib import Path

from app.automation import AutomationEngine
from app.config import Settings
from app.db import Database
from app.tools.registry import ToolRegistry


def make_stack(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        static_dir=Path(__file__).resolve().parents[1] / "app" / "static",
        default_model="fake-model",
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.database_path)
    tools = ToolRegistry(settings, db)
    return settings, db, tools


def test_project_task_and_run_lifecycle(tmp_path: Path) -> None:
    _, db, _ = make_stack(tmp_path)
    project = db.create_project("DPN Core", "Upgrade the core", ".")
    task = db.create_task(project["id"], "Add task board", "Persistent states", "high", [])
    updated = db.update_task(task["id"], {"status": "done", "result": {"tests": "passed"}})
    assert updated is not None
    assert updated["status"] == "done"
    assert updated["result"]["tests"] == "passed"
    assert db.task_counts(project["id"])["done"] == 1

    conversation_id = db.create_conversation("Upgrade")
    run_id = db.create_run(conversation_id, project["id"], "Upgrade DPN AI", "director", "fake-model")
    db.finish_run(run_id, "completed", [{"name": "test", "ok": True}], "Finished")
    run = db.list_runs(1)[0]
    assert run["status"] == "completed"
    assert run["traces"][0]["name"] == "test"


def test_snapshot_create_and_restore(tmp_path: Path) -> None:
    _, _, tools = make_stack(tmp_path)
    source = tools.fs.resolve("project/config.txt")
    source.parent.mkdir(parents=True)
    source.write_text("version=1", encoding="utf-8")
    snapshot = tools.snapshots.create("baseline", "project")
    assert snapshot["ok"] is True
    assert snapshot["manifest"]["file_count"] == 1

    source.write_text("version=2", encoding="utf-8")
    restored = tools.snapshots.restore(snapshot["id"], overwrite=True)
    assert restored["ok"] is True
    assert source.read_text(encoding="utf-8") == "version=1"


def test_approval_modes_block_risky_tools(tmp_path: Path) -> None:
    _, _, tools = make_stack(tmp_path)
    tools.fs.write_file("delete-me.txt", "data")
    safe_result = asyncio.run(tools.execute("delete_path", {"path": "delete-me.txt"}, {"approval_mode": "safe"}))
    assert safe_result["ok"] is False
    assert tools.fs.resolve("delete-me.txt").exists()

    standard_result = asyncio.run(tools.execute("delete_path", {"path": "delete-me.txt"}, {"approval_mode": "standard"}))
    assert standard_result["ok"] is False

    autonomous_result = asyncio.run(tools.execute("delete_path", {"path": "delete-me.txt"}, {"approval_mode": "autonomous"}))
    assert autonomous_result["ok"] is True
    assert not tools.fs.resolve("delete-me.txt").exists()


class FakeAgent:
    settings = type("SettingsStub", (), {"allow_automations_default": False})()


def test_automation_schedule_validation(tmp_path: Path) -> None:
    _, db, _ = make_stack(tmp_path)
    engine = AutomationEngine(db, FakeAgent())
    assert engine.validate("interval", "15")
    assert engine.validate("daily", "08:30")
    try:
        engine.validate("daily", "99:99")
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid daily time should fail")