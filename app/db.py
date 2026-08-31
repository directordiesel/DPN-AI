from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.init()
        self.init_v3()
        self.init_v5()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init(self) -> None:
        with self._lock, self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);

                CREATE TABLE IF NOT EXISTS memories (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE NOT NULL,
                    modified_ns INTEGER NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    indexed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding_json TEXT,
                    FOREIGN KEY(document_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                    content,
                    path UNINDEXED,
                    chunk_id UNINDEXED,
                    tokenize='porter unicode61'
                );

                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    root_path TEXT NOT NULL DEFAULT '.',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS project_tasks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'backlog',
                    priority TEXT NOT NULL DEFAULT 'normal',
                    dependencies_json TEXT NOT NULL DEFAULT '[]',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_project_tasks_project ON project_tasks(project_id, status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS operation_runs (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT,
                    project_id TEXT,
                    objective TEXT NOT NULL,
                    profile TEXT NOT NULL DEFAULT 'auto',
                    model TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'running',
                    trace_json TEXT NOT NULL DEFAULT '[]',
                    result_text TEXT NOT NULL DEFAULT '',
                    error_text TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE SET NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_operation_runs_created ON operation_runs(created_at DESC);

                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT 'system',
                    summary TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_events_created ON audit_events(created_at DESC);

                CREATE TABLE IF NOT EXISTS workspace_snapshots (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    archive_path TEXT NOT NULL,
                    manifest_json TEXT NOT NULL DEFAULT '{}',
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS automations (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    schedule_type TEXT NOT NULL,
                    schedule_value TEXT NOT NULL,
                    profile TEXT NOT NULL DEFAULT 'auto',
                    project_id TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_run_at TEXT,
                    next_run_at TEXT,
                    last_status TEXT,
                    last_result TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
                );
                """
            )

    # Conversations
    def create_conversation(self, title: str = "New conversation") -> str:
        conversation_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute(
                "INSERT INTO conversations(id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conversation_id, title.strip() or "New conversation", now, now),
            )
        return conversation_id

    def ensure_conversation(self, conversation_id: str | None, title_hint: str = "New conversation") -> str:
        if conversation_id:
            with self.connect() as db:
                found = db.execute("SELECT id FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
            if found:
                return conversation_id
        title = title_hint.strip().replace("\n", " ")[:70] or "New conversation"
        return self.create_conversation(title)

    def list_conversations(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def rename_conversation(self, conversation_id: str, title: str) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
                (title.strip()[:120], utc_now(), conversation_id),
            )
        return cursor.rowcount > 0

    def delete_conversation(self, conversation_id: str) -> bool:
        with self.connect() as db:
            cursor = db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return cursor.rowcount > 0

    def add_message(self, conversation_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> int:
        now = utc_now()
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO messages(conversation_id, role, content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, role, content, _json(metadata or {}), now),
            )
            db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        return int(cursor.lastrowid)

    def get_messages(self, conversation_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT id, role, content, metadata_json, created_at
                FROM (
                    SELECT id, role, content, metadata_json, created_at
                    FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?
                ) ORDER BY id ASC
                """,
                (conversation_id, limit),
            ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            except json.JSONDecodeError:
                item["metadata"] = {}
            output.append(item)
        return output

    def truncate_from_message(self, conversation_id: str, message_id: int) -> dict[str, Any]:
        """Remove one user message and every later message so it can be edited and regenerated."""
        with self.connect() as db:
            row = db.execute(
                "SELECT id, role, content FROM messages WHERE id=? AND conversation_id=?",
                (message_id, conversation_id),
            ).fetchone()
            if not row:
                return {"ok": False, "error": "Message not found in this conversation."}
            if row["role"] != "user":
                return {"ok": False, "error": "Only user messages can be edited and regenerated."}
            deleted = db.execute(
                "DELETE FROM messages WHERE conversation_id=? AND id>=?",
                (conversation_id, message_id),
            ).rowcount
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (utc_now(), conversation_id))
        self.audit("conversation.message_edited", "Truncated conversation for edit and regeneration", {
            "conversation_id": conversation_id, "message_id": message_id, "deleted_messages": deleted,
        }, actor="user")
        return {"ok": True, "deleted_messages": deleted, "original_content": row["content"]}

    # Memory and settings
    def upsert_memory(self, key: str, value: str) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO memories(key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key.strip(), value.strip(), utc_now()),
            )

    def delete_memory(self, key: str) -> bool:
        with self.connect() as db:
            cursor = db.execute("DELETE FROM memories WHERE key = ?", (key,))
        return cursor.rowcount > 0

    def list_memories(self) -> list[dict[str, str]]:
        with self.connect() as db:
            rows = db.execute("SELECT key, value, updated_at FROM memories ORDER BY updated_at DESC").fetchall()
        return [dict(row) for row in rows]

    def memory_context(self, max_chars: int = 16_000) -> str:
        parts: list[str] = []
        total = 0
        for item in self.list_memories():
            line = f"- {item['key']}: {item['value']}"
            if total + len(line) > max_chars:
                break
            parts.append(line)
            total += len(line)
        return "\n".join(parts)

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.connect() as db:
            row = db.execute("SELECT value_json FROM app_settings WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value_json"])
        except json.JSONDecodeError:
            return default

    def set_setting(self, key: str, value: Any) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO app_settings(key, value_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
                """,
                (key, _json(value), utc_now()),
            )

    def all_settings(self) -> dict[str, Any]:
        with self.connect() as db:
            rows = db.execute("SELECT key, value_json FROM app_settings").fetchall()
        values: dict[str, Any] = {}
        for row in rows:
            try:
                values[row["key"]] = json.loads(row["value_json"])
            except json.JSONDecodeError:
                continue
        return values

    # Projects and tasks
    def create_project(self, name: str, description: str = "", root_path: str = ".") -> dict[str, Any]:
        project_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute(
                "INSERT INTO projects(id,name,description,root_path,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (project_id, name.strip(), description.strip(), root_path.strip() or ".", "active", now, now),
            )
        self.audit("project.created", f"Created project {name}", {"project_id": project_id, "root_path": root_path})
        return self.get_project(project_id) or {}

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return dict(row) if row else None

    def list_projects(self, include_archived: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM projects"
        args: tuple[Any, ...] = ()
        if not include_archived:
            query += " WHERE status != ?"
            args = ("archived",)
        query += " ORDER BY updated_at DESC"
        with self.connect() as db:
            rows = db.execute(query, args).fetchall()
        projects = [dict(row) for row in rows]
        for project in projects:
            project["task_counts"] = self.task_counts(project["id"])
        return projects

    def update_project(self, project_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"name", "description", "root_path", "status"}
        updates = {k: v for k, v in values.items() if k in allowed and v is not None}
        if not updates:
            return self.get_project(project_id)
        updates["updated_at"] = utc_now()
        clause = ", ".join(f"{key}=?" for key in updates)
        with self.connect() as db:
            db.execute(f"UPDATE projects SET {clause} WHERE id=?", (*updates.values(), project_id))
        self.audit("project.updated", f"Updated project {project_id}", updates)
        return self.get_project(project_id)

    def create_task(self, project_id: str, title: str, details: str = "", priority: str = "normal", dependencies: list[str] | None = None) -> dict[str, Any]:
        task_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """INSERT INTO project_tasks(id,project_id,title,details,status,priority,dependencies_json,result_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (task_id, project_id, title.strip(), details.strip(), "backlog", priority, _json(dependencies or []), "{}", now, now),
            )
            db.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, project_id))
        self.audit("task.created", f"Created task {title}", {"project_id": project_id, "task_id": task_id})
        return self.get_task(task_id) or {}

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM project_tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return None
        return self._task_dict(row)

    @staticmethod
    def _task_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        for field, fallback in (("dependencies_json", []), ("result_json", {})):
            try:
                item[field.removesuffix("_json")] = json.loads(item.pop(field) or _json(fallback))
            except json.JSONDecodeError:
                item[field.removesuffix("_json")] = fallback
        return item

    def list_tasks(self, project_id: str, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM project_tasks WHERE project_id=?"
        args: list[Any] = [project_id]
        if status:
            query += " AND status=?"
            args.append(status)
        query += " ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, updated_at DESC"
        with self.connect() as db:
            rows = db.execute(query, tuple(args)).fetchall()
        return [self._task_dict(row) for row in rows]

    def update_task(self, task_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"title", "details", "status", "priority"}
        updates = {k: v for k, v in values.items() if k in allowed and v is not None}
        if values.get("result") is not None:
            updates["result_json"] = _json(values["result"])
        if not updates:
            return self.get_task(task_id)
        updates["updated_at"] = utc_now()
        clause = ", ".join(f"{key}=?" for key in updates)
        with self.connect() as db:
            row = db.execute("SELECT project_id FROM project_tasks WHERE id=?", (task_id,)).fetchone()
            db.execute(f"UPDATE project_tasks SET {clause} WHERE id=?", (*updates.values(), task_id))
            if row:
                db.execute("UPDATE projects SET updated_at=? WHERE id=?", (utc_now(), row["project_id"]))
        self.audit("task.updated", f"Updated task {task_id}", updates)
        return self.get_task(task_id)

    def delete_task(self, task_id: str) -> bool:
        with self.connect() as db:
            cursor = db.execute("DELETE FROM project_tasks WHERE id=?", (task_id,))
        if cursor.rowcount:
            self.audit("task.deleted", f"Deleted task {task_id}")
        return cursor.rowcount > 0

    def task_counts(self, project_id: str) -> dict[str, int]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT status, COUNT(*) AS count FROM project_tasks WHERE project_id=? GROUP BY status",
                (project_id,),
            ).fetchall()
        counts = {"total": 0, "backlog": 0, "ready": 0, "running": 0, "blocked": 0, "done": 0, "failed": 0}
        for row in rows:
            counts[row["status"]] = int(row["count"])
            counts["total"] += int(row["count"])
        return counts

    def project_context(self, project_id: str | None, max_tasks: int = 20) -> str:
        if not project_id:
            return ""
        project = self.get_project(project_id)
        if not project:
            return ""
        tasks = self.list_tasks(project_id)[:max_tasks]
        lines = [
            f"Project: {project['name']}",
            f"Status: {project['status']}",
            f"Workspace root: {project['root_path']}",
            f"Description: {project['description'] or '(none)'}",
            "Tasks:",
        ]
        lines.extend(f"- [{task['status']}] ({task['priority']}) {task['title']} — id {task['id']}" for task in tasks)
        return "\n".join(lines)

    # Operation runs and audit
    def create_run(self, conversation_id: str | None, project_id: str | None, objective: str, profile: str, model: str) -> str:
        run_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute(
                """INSERT INTO operation_runs(id,conversation_id,project_id,objective,profile,model,status,created_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (run_id, conversation_id, project_id, objective, profile, model, "running", utc_now()),
            )
        self.audit("run.started", f"Started operation: {objective[:120]}", {"run_id": run_id, "profile": profile, "project_id": project_id})
        return run_id

    def finish_run(self, run_id: str, status: str, traces: list[dict[str, Any]], result_text: str = "", error_text: str = "") -> None:
        with self.connect() as db:
            db.execute(
                """UPDATE operation_runs SET status=?, trace_json=?, result_text=?, error_text=?, completed_at=? WHERE id=?""",
                (status, _json(traces), result_text, error_text, utc_now(), run_id),
            )
        self.audit("run.finished", f"Operation {status}", {"run_id": run_id, "trace_count": len(traces)})

    def list_runs(self, limit: int = 100, project_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM operation_runs"
        args: list[Any] = []
        if project_id:
            query += " WHERE project_id=?"
            args.append(project_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        args.append(max(1, min(limit, 500)))
        with self.connect() as db:
            rows = db.execute(query, tuple(args)).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["traces"] = json.loads(item.pop("trace_json") or "[]")
            except json.JSONDecodeError:
                item["traces"] = []
            output.append(item)
        return output

    def audit(self, event_type: str, summary: str, metadata: dict[str, Any] | None = None, actor: str = "system") -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO audit_events(event_type,actor,summary,metadata_json,created_at) VALUES (?,?,?,?,?)",
                (event_type, actor, summary, _json(metadata or {}), utc_now()),
            )

    def list_audit(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 1000)),),
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            except json.JSONDecodeError:
                item["metadata"] = {}
            output.append(item)
        return output

    # Snapshots
    def add_snapshot(self, name: str, source_path: str, archive_path: str, manifest: dict[str, Any], size_bytes: int) -> dict[str, Any]:
        snapshot_id = str(uuid.uuid4())
        created_at = utc_now()
        with self.connect() as db:
            db.execute(
                "INSERT INTO workspace_snapshots(id,name,source_path,archive_path,manifest_json,size_bytes,created_at) VALUES (?,?,?,?,?,?,?)",
                (snapshot_id, name, source_path, archive_path, _json(manifest), size_bytes, created_at),
            )
        self.audit("snapshot.created", f"Created snapshot {name}", {"snapshot_id": snapshot_id, "source_path": source_path})
        return {"id": snapshot_id, "name": name, "source_path": source_path, "archive_path": archive_path, "manifest": manifest, "size_bytes": size_bytes, "created_at": created_at}

    def list_snapshots(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM workspace_snapshots ORDER BY created_at DESC").fetchall()
        output = []
        for row in rows:
            item = dict(row)
            try:
                item["manifest"] = json.loads(item.pop("manifest_json") or "{}")
            except json.JSONDecodeError:
                item["manifest"] = {}
            output.append(item)
        return output

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM workspace_snapshots WHERE id=?", (snapshot_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["manifest"] = json.loads(item.pop("manifest_json") or "{}")
        return item

    # Automations
    def create_automation(self, values: dict[str, Any]) -> dict[str, Any]:
        automation_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """INSERT INTO automations(id,name,prompt,schedule_type,schedule_value,profile,project_id,enabled,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    automation_id, values["name"], values["prompt"], values["schedule_type"], values["schedule_value"],
                    values.get("profile", "auto"), values.get("project_id"), 1 if values.get("enabled", True) else 0, now, now,
                ),
            )
        self.audit("automation.created", f"Created automation {values['name']}", {"automation_id": automation_id})
        return self.get_automation(automation_id) or {}

    def get_automation(self, automation_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM automations WHERE id=?", (automation_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        return item

    def list_automations(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM automations ORDER BY updated_at DESC").fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["enabled"] = bool(item["enabled"])
            output.append(item)
        return output

    def update_automation(self, automation_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"name", "prompt", "schedule_type", "schedule_value", "profile", "project_id", "enabled", "last_run_at", "next_run_at", "last_status", "last_result"}
        updates = {k: v for k, v in values.items() if k in allowed and v is not None}
        if "enabled" in updates:
            updates["enabled"] = 1 if updates["enabled"] else 0
        if not updates:
            return self.get_automation(automation_id)
        updates["updated_at"] = utc_now()
        clause = ", ".join(f"{key}=?" for key in updates)
        with self.connect() as db:
            db.execute(f"UPDATE automations SET {clause} WHERE id=?", (*updates.values(), automation_id))
        return self.get_automation(automation_id)

    def delete_automation(self, automation_id: str) -> bool:
        with self.connect() as db:
            cursor = db.execute("DELETE FROM automations WHERE id=?", (automation_id,))
        if cursor.rowcount:
            self.audit("automation.deleted", f"Deleted automation {automation_id}")
        return cursor.rowcount > 0


    # DPN AI v3 universal mission control
    def init_v3(self) -> None:
        with self._lock, self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS missions (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT,
                    project_id TEXT,
                    objective TEXT NOT NULL,
                    execution_mode TEXT NOT NULL DEFAULT 'mission',
                    status TEXT NOT NULL DEFAULT 'planning',
                    planner_model TEXT NOT NULL DEFAULT '',
                    worker_model TEXT NOT NULL DEFAULT '',
                    reviewer_model TEXT NOT NULL DEFAULT '',
                    budget_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE SET NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_missions_created ON missions(created_at DESC);

                CREATE TABLE IF NOT EXISTS mission_steps (
                    id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    role TEXT NOT NULL DEFAULT 'director',
                    title TEXT NOT NULL,
                    instructions TEXT NOT NULL DEFAULT '',
                    dependencies_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(mission_id) REFERENCES missions(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_mission_steps_mission ON mission_steps(mission_id, ordinal);

                CREATE TABLE IF NOT EXISTS approval_requests (
                    id TEXT PRIMARY KEY,
                    run_id TEXT,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL DEFAULT '{}',
                    risk TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_approvals_status ON approval_requests(status, created_at DESC);

                CREATE TABLE IF NOT EXISTS semantic_items (
                    id TEXT PRIMARY KEY,
                    namespace TEXT NOT NULL DEFAULT 'global',
                    source TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    vector_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_semantic_namespace ON semantic_items(namespace, updated_at DESC);

                CREATE TABLE IF NOT EXISTS connectors (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL DEFAULT 'http',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workflows (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    steps_json TEXT NOT NULL DEFAULT '[]',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workflow_runs (
                    id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running',
                    inputs_json TEXT NOT NULL DEFAULT '{}',
                    outputs_json TEXT NOT NULL DEFAULT '{}',
                    error_text TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY(workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS webhook_events (
                    id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    processed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                """
            )

    # Missions
    def create_mission(self, objective: str, conversation_id: str | None = None, project_id: str | None = None,
                       execution_mode: str = "mission", models: dict[str, str] | None = None,
                       budget: dict[str, Any] | None = None) -> dict[str, Any]:
        mission_id = str(uuid.uuid4())
        now = utc_now()
        models = models or {}
        with self.connect() as db:
            db.execute(
                """INSERT INTO missions(id,conversation_id,project_id,objective,execution_mode,status,planner_model,
                worker_model,reviewer_model,budget_json,result_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (mission_id, conversation_id, project_id, objective, execution_mode, "planning",
                 models.get("planner", ""), models.get("worker", ""), models.get("reviewer", ""),
                 _json(budget or {}), "{}", now, now),
            )
        self.audit("mission.created", f"Created mission: {objective[:120]}", {"mission_id": mission_id})
        return self.get_mission(mission_id) or {}

    def get_mission(self, mission_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        for field in ("budget_json", "result_json"):
            try:
                item[field.removesuffix("_json")] = json.loads(item.pop(field) or "{}")
            except json.JSONDecodeError:
                item[field.removesuffix("_json")] = {}
        item["steps"] = self.list_mission_steps(mission_id)
        return item

    def list_missions(self, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM missions"
        args: list[Any] = []
        if status:
            query += " WHERE status=?"
            args.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        args.append(max(1, min(limit, 1000)))
        with self.connect() as db:
            rows = db.execute(query, tuple(args)).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            for field in ("budget_json", "result_json"):
                try:
                    item[field.removesuffix("_json")] = json.loads(item.pop(field) or "{}")
                except json.JSONDecodeError:
                    item[field.removesuffix("_json")] = {}
            output.append(item)
        return output

    def update_mission(self, mission_id: str, status: str | None = None, result: dict[str, Any] | None = None) -> dict[str, Any] | None:
        updates: dict[str, Any] = {"updated_at": utc_now()}
        if status is not None:
            updates["status"] = status
            if status in {"completed", "failed", "cancelled"}:
                updates["completed_at"] = utc_now()
        if result is not None:
            updates["result_json"] = _json(result)
        clause = ", ".join(f"{key}=?" for key in updates)
        with self.connect() as db:
            db.execute(f"UPDATE missions SET {clause} WHERE id=?", (*updates.values(), mission_id))
        return self.get_mission(mission_id)

    def add_mission_step(self, mission_id: str, ordinal: int, role: str, title: str, instructions: str,
                         dependencies: list[str] | None = None) -> dict[str, Any]:
        step_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """INSERT INTO mission_steps(id,mission_id,ordinal,role,title,instructions,dependencies_json,status,
                attempts,result_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (step_id, mission_id, ordinal, role, title, instructions, _json(dependencies or []), "pending", 0, "{}", now, now),
            )
        return self.get_mission_step(step_id) or {}

    def get_mission_step(self, step_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM mission_steps WHERE id=?", (step_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        for field, fallback in (("dependencies_json", []), ("result_json", {})):
            try:
                item[field.removesuffix("_json")] = json.loads(item.pop(field) or _json(fallback))
            except json.JSONDecodeError:
                item[field.removesuffix("_json")] = fallback
        return item

    def list_mission_steps(self, mission_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM mission_steps WHERE mission_id=? ORDER BY ordinal", (mission_id,)).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            for field, fallback in (("dependencies_json", []), ("result_json", {})):
                try:
                    item[field.removesuffix("_json")] = json.loads(item.pop(field) or _json(fallback))
                except json.JSONDecodeError:
                    item[field.removesuffix("_json")] = fallback
            output.append(item)
        return output

    def update_mission_step(self, step_id: str, status: str | None = None, result: dict[str, Any] | None = None,
                            increment_attempts: bool = False) -> dict[str, Any] | None:
        updates: dict[str, Any] = {"updated_at": utc_now()}
        if status is not None:
            updates["status"] = status
        if result is not None:
            updates["result_json"] = _json(result)
        clause = ", ".join(f"{key}=?" for key in updates)
        with self.connect() as db:
            if increment_attempts:
                db.execute("UPDATE mission_steps SET attempts=attempts+1 WHERE id=?", (step_id,))
            db.execute(f"UPDATE mission_steps SET {clause} WHERE id=?", (*updates.values(), step_id))
        return self.get_mission_step(step_id)

    # Approval inbox
    def create_approval(self, tool_name: str, arguments: dict[str, Any], risk: str, reason: str,
                        run_id: str | None = None) -> dict[str, Any]:
        approval_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute(
                "INSERT INTO approval_requests(id,run_id,tool_name,arguments_json,risk,reason,status,result_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (approval_id, run_id, tool_name, _json(arguments), risk, reason, "pending", "{}", now),
            )
        self.audit("approval.requested", f"Approval required for {tool_name}", {"approval_id": approval_id, "risk": risk})
        return self.get_approval(approval_id) or {}

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM approval_requests WHERE id=?", (approval_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        for field in ("arguments_json", "result_json"):
            try:
                item[field.removesuffix("_json")] = json.loads(item.pop(field) or "{}")
            except json.JSONDecodeError:
                item[field.removesuffix("_json")] = {}
        return item

    def list_approvals(self, status: str | None = "pending", limit: int = 200) -> list[dict[str, Any]]:
        query = "SELECT * FROM approval_requests"
        args: list[Any] = []
        if status:
            query += " WHERE status=?"
            args.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        args.append(max(1, min(limit, 1000)))
        with self.connect() as db:
            rows = db.execute(query, tuple(args)).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            for field in ("arguments_json", "result_json"):
                try:
                    item[field.removesuffix("_json")] = json.loads(item.pop(field) or "{}")
                except json.JSONDecodeError:
                    item[field.removesuffix("_json")] = {}
            output.append(item)
        return output

    def resolve_approval(self, approval_id: str, status: str, result: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if status not in {"approved", "denied", "executed", "failed"}:
            raise ValueError("Invalid approval status")
        with self.connect() as db:
            db.execute(
                "UPDATE approval_requests SET status=?, result_json=?, resolved_at=? WHERE id=?",
                (status, _json(result or {}), utc_now(), approval_id),
            )
        self.audit(f"approval.{status}", f"Approval {status}: {approval_id}")
        return self.get_approval(approval_id)

    # Semantic items
    def upsert_semantic_item(self, item_id: str, namespace: str, source: str, content: str,
                             vector: list[float], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """INSERT INTO semantic_items(id,namespace,source,content,vector_json,metadata_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET namespace=excluded.namespace,source=excluded.source,
                content=excluded.content,vector_json=excluded.vector_json,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at""",
                (item_id, namespace, source, content, _json(vector), _json(metadata or {}), now, now),
            )
        return self.get_semantic_item(item_id) or {}

    def get_semantic_item(self, item_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM semantic_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["vector"] = json.loads(item.pop("vector_json") or "[]")
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        return item

    def list_semantic_items(self, namespace: str = "global", limit: int = 5000) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM semantic_items WHERE namespace=? ORDER BY updated_at DESC LIMIT ?", (namespace, limit)).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            try:
                item["vector"] = json.loads(item.pop("vector_json") or "[]")
                item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            except json.JSONDecodeError:
                item["vector"], item["metadata"] = [], {}
            output.append(item)
        return output

    def delete_semantic_item(self, item_id: str) -> bool:
        with self.connect() as db:
            cursor = db.execute("DELETE FROM semantic_items WHERE id=?", (item_id,))
        return cursor.rowcount > 0

    # Connectors
    def create_connector(self, name: str, kind: str, config: dict[str, Any], enabled: bool = True) -> dict[str, Any]:
        connector_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute("INSERT INTO connectors(id,name,kind,config_json,enabled,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                       (connector_id, name, kind, _json(config), 1 if enabled else 0, now, now))
        return self.get_connector(connector_id) or {}

    def get_connector(self, connector_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM connectors WHERE id=?", (connector_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        item["config"] = json.loads(item.pop("config_json") or "{}")
        return item

    def list_connectors(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM connectors ORDER BY updated_at DESC").fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["enabled"] = bool(item["enabled"])
            item["config"] = json.loads(item.pop("config_json") or "{}")
            output.append(item)
        return output

    def delete_connector(self, connector_id: str) -> bool:
        with self.connect() as db:
            cursor = db.execute("DELETE FROM connectors WHERE id=?", (connector_id,))
        return cursor.rowcount > 0

    # Reusable workflows
    def create_workflow(self, name: str, description: str, steps: list[dict[str, Any]], enabled: bool = True) -> dict[str, Any]:
        workflow_id = str(uuid.uuid4())
        now = utc_now()        with self.connect() as db:
            db.execute("INSERT INTO workflows(id,name,description,steps_json,enabled,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                       (workflow_id, name, description, _json(steps), 1 if enabled else 0, now, now))
        return self.get_workflow(workflow_id) or {}

    def get_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM workflows WHERE id=?", (workflow_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        item["steps"] = json.loads(item.pop("steps_json") or "[]")
        return item

    def list_workflows(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM workflows ORDER BY updated_at DESC").fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["enabled"] = bool(item["enabled"])
            item["steps"] = json.loads(item.pop("steps_json") or "[]")
            output.append(item)
        return output

    def create_workflow_run(self, workflow_id: str, inputs: dict[str, Any]) -> str:
        run_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO workflow_runs(id,workflow_id,status,inputs_json,outputs_json,error_text,created_at) VALUES (?,?,?,?,?,?,?)",
                       (run_id, workflow_id, "running", _json(inputs), "{}", "", utc_now()))
        return run_id

    def finish_workflow_run(self, run_id: str, status: str, outputs: dict[str, Any] | None = None, error: str = "") -> None:
        with self.connect() as db:
            db.execute("UPDATE workflow_runs SET status=?,outputs_json=?,error_text=?,completed_at=? WHERE id=?",
                       (status, _json(outputs or {}), error, utc_now(), run_id))

    def add_webhook_event(self, topic: str, payload: dict[str, Any]) -> dict[str, Any]:
        event_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO webhook_events(id,topic,payload_json,processed,created_at) VALUES (?,?,?,?,?)",
                       (event_id, topic, _json(payload), 0, utc_now()))
        return {"id": event_id, "topic": topic, "payload": payload, "processed": False}


    # DPN AI v5 cognitive kernel, graph memory, MCP, and resilient jobs
    def init_v5(self) -> None:
        with self._lock, self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS goal_contracts (
                    mission_id TEXT PRIMARY KEY,
                    contract_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(mission_id) REFERENCES missions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS graph_nodes (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    label TEXT NOT NULL,
                    normalized_label TEXT NOT NULL,
                    node_type TEXT NOT NULL DEFAULT 'entity',
                    data_json TEXT NOT NULL DEFAULT '{}',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    source TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_graph_nodes_label ON graph_nodes(normalized_label, node_type);
                CREATE INDEX IF NOT EXISTS idx_graph_nodes_project ON graph_nodes(project_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS graph_edges (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    data_json TEXT NOT NULL DEFAULT '{}',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    source TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(source_id) REFERENCES graph_nodes(id) ON DELETE CASCADE,
                    FOREIGN KEY(target_id) REFERENCES graph_nodes(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source_id, relation);
                CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target_id, relation);

                CREATE TABLE IF NOT EXISTS mission_checkpoints (
                    id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    step_id TEXT,
                    label TEXT NOT NULL,
                    state_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(mission_id) REFERENCES missions(id) ON DELETE CASCADE,
                    FOREIGN KEY(step_id) REFERENCES mission_steps(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_mission_checkpoints ON mission_checkpoints(mission_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS evaluation_runs (
                    id TEXT PRIMARY KEY,
                    mission_id TEXT,
                    evaluator TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    score REAL NOT NULL DEFAULT 0.0,
                    report_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(mission_id) REFERENCES missions(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_evaluation_runs_mission ON evaluation_runs(mission_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS background_jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'queued',
                    progress_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error_text TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_background_jobs_status ON background_jobs(status, created_at);

                CREATE TABLE IF NOT EXISTS mcp_servers (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    transport TEXT NOT NULL,
                    config_json TEXT NOT NULL DEFAULT '{}',
                    allowed_tools_json TEXT NOT NULL DEFAULT '[]',
                    tools_json TEXT NOT NULL DEFAULT '[]',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_mcp_servers_enabled ON mcp_servers(enabled, updated_at DESC);

                CREATE TABLE IF NOT EXISTS mcp_calls (
                    id TEXT PRIMARY KEY,
                    server_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    ok INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(server_id) REFERENCES mcp_servers(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_mcp_calls_server ON mcp_calls(server_id, created_at DESC);
                """
            )

    # Goal contracts and mission evidence
    def upsert_goal_contract(self, mission_id: str, contract: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """INSERT INTO goal_contracts(mission_id,contract_json,created_at,updated_at) VALUES (?,?,?,?)
                ON CONFLICT(mission_id) DO UPDATE SET contract_json=excluded.contract_json,updated_at=excluded.updated_at""",
                (mission_id, _json(contract), now, now),
            )
        return self.get_goal_contract(mission_id) or {}

    def get_goal_contract(self, mission_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM goal_contracts WHERE mission_id=?", (mission_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["contract"] = json.loads(item.pop("contract_json") or "{}")
        return item

    def add_checkpoint(self, mission_id: str, label: str, state: dict[str, Any], step_id: str | None = None) -> dict[str, Any]:
        checkpoint_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute(
                "INSERT INTO mission_checkpoints(id,mission_id,step_id,label,state_json,created_at) VALUES (?,?,?,?,?,?)",
                (checkpoint_id, mission_id, step_id, label[:240], _json(state), utc_now()),
            )
        return {"id": checkpoint_id, "mission_id": mission_id, "step_id": step_id, "label": label[:240], "state": state}

    def list_checkpoints(self, mission_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM mission_checkpoints WHERE mission_id=? ORDER BY created_at DESC LIMIT ?",
                (mission_id, max(1, min(limit, 1000))),
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["state"] = json.loads(item.pop("state_json") or "{}")
            output.append(item)
        return output

    def add_evaluation(self, mission_id: str | None, evaluator: str, verdict: str, score: float,
                       report: dict[str, Any]) -> dict[str, Any]:
        evaluation_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute(
                "INSERT INTO evaluation_runs(id,mission_id,evaluator,verdict,score,report_json,created_at) VALUES (?,?,?,?,?,?,?)",
                (evaluation_id, mission_id, evaluator[:120], verdict[:20], max(0.0, min(float(score), 1.0)), _json(report), utc_now()),
            )
        return {"id": evaluation_id, "mission_id": mission_id, "evaluator": evaluator, "verdict": verdict, "score": score, "report": report}

    def list_evaluations(self, mission_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM evaluation_runs WHERE mission_id=? ORDER BY created_at DESC LIMIT ?",
                (mission_id, max(1, min(limit, 1000))),
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["report"] = json.loads(item.pop("report_json") or "{}")
            output.append(item)
        return output

    # Provenance-aware knowledge graph
    @staticmethod
    def _normalize_graph_label(label: str) -> str:
        return " ".join(str(label).strip().lower().split())[:500]

    def upsert_graph_node(self, label: str, node_type: str = "entity", data: dict[str, Any] | None = None,
                          confidence: float = 1.0, source: str = "manual", project_id: str | None = None,
                          node_id: str | None = None) -> dict[str, Any]:
        normalized = self._normalize_graph_label(label)
        with self.connect() as db:
            row = db.execute(
                "SELECT id FROM graph_nodes WHERE normalized_label=? AND node_type=? AND COALESCE(project_id,'')=COALESCE(?,'') LIMIT 1",
                (normalized, node_type, project_id),
            ).fetchone()
            existing_id = row["id"] if row else None
        target_id = node_id or existing_id or str(uuid.uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """INSERT INTO graph_nodes(id,project_id,label,normalized_label,node_type,data_json,confidence,source,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET project_id=excluded.project_id,label=excluded.label,
                normalized_label=excluded.normalized_label,node_type=excluded.node_type,data_json=excluded.data_json,
                confidence=excluded.confidence,source=excluded.source,updated_at=excluded.updated_at""",
                (target_id, project_id, label[:500], normalized, node_type[:80], _json(data or {}), confidence, source[:1000], now, now),
            )
        return self.get_graph_node(target_id) or {}

    def get_graph_node(self, node_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM graph_nodes WHERE id=?", (node_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["data"] = json.loads(item.pop("data_json") or "{}")
        return item

    def search_graph_nodes(self, query: str, project_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        pattern = f"%{self._normalize_graph_label(query)}%"
        sql = "SELECT * FROM graph_nodes WHERE normalized_label LIKE ?"
        args: list[Any] = [pattern]
        if project_id:
            sql += " AND (project_id=? OR project_id IS NULL)"
            args.append(project_id)
        sql += " ORDER BY confidence DESC, updated_at DESC LIMIT ?"
        args.append(max(1, min(limit, 500)))
        with self.connect() as db:
            rows = db.execute(sql, tuple(args)).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["data"] = json.loads(item.pop("data_json") or "{}")
            output.append(item)
        return output

    def add_graph_edge(self, source_id: str, relation: str, target_id: str, data: dict[str, Any] | None = None,
                       confidence: float = 1.0, source: str = "manual") -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute(
                "SELECT id FROM graph_edges WHERE source_id=? AND relation=? AND target_id=? LIMIT 1",
                (source_id, relation, target_id),
            ).fetchone()
        edge_id = row["id"] if row else str(uuid.uuid4())
        with self.connect() as db:
            if row:
                db.execute(
                    "UPDATE graph_edges SET data_json=?,confidence=?,source=? WHERE id=?",
                    (_json(data or {}), confidence, source[:1000], edge_id),
                )
            else:
                db.execute(
                    "INSERT INTO graph_edges(id,source_id,relation,target_id,data_json,confidence,source,created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (edge_id, source_id, relation[:120], target_id, _json(data or {}), confidence, source[:1000], utc_now()),
                )
        with self.connect() as db:
            edge = db.execute("SELECT * FROM graph_edges WHERE id=?", (edge_id,)).fetchone()
        item = dict(edge)
        item["data"] = json.loads(item.pop("data_json") or "{}")
        return item

    def graph_neighborhood(self, node_id: str, depth: int = 1, limit: int = 100) -> dict[str, Any]:
        depth = max(1, min(int(depth), 4))
        limit = max(1, min(int(limit), 1000))
        visited = {node_id}
        frontier = {node_id}
        edges: list[dict[str, Any]] = []
        for _ in range(depth):
            if not frontier or len(edges) >= limit:
                break
            placeholders = ",".join("?" for _ in frontier)
            with self.connect() as db:
                rows = db.execute(
                    f"SELECT * FROM graph_edges WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders}) LIMIT ?",
                    (*frontier, *frontier, limit - len(edges)),
                ).fetchall()
            next_frontier: set[str] = set()
            for row in rows:
                item = dict(row)
                item["data"] = json.loads(item.pop("data_json") or "{}")
                if item["id"] not in {edge["id"] for edge in edges}:
                    edges.append(item)
                for candidate in (item["source_id"], item["target_id"]):
                    if candidate not in visited:
                        visited.add(candidate)
                        next_frontier.add(candidate)
            frontier = next_frontier
        nodes = [self.get_graph_node(item) for item in visited]
        return {"nodes": [item for item in nodes if item], "edges": edges[:limit]}

    def graph_stats(self) -> dict[str, Any]:
        with self.connect() as db:
            nodes = int(db.execute("SELECT COUNT(*) AS count FROM graph_nodes").fetchone()["count"])
            edges = int(db.execute("SELECT COUNT(*) AS count FROM graph_edges").fetchone()["count"])
            types = [dict(row) for row in db.execute("SELECT node_type,COUNT(*) AS count FROM graph_nodes GROUP BY node_type ORDER BY count DESC").fetchall()]
        return {"nodes": nodes, "edges": edges, "types": types}

    # Background job persistence
    def create_background_job(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute(
                "INSERT INTO background_jobs(id,kind,payload_json,status,progress_json,result_json,error_text,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (job_id, kind[:80], _json(payload), "queued", "{}", "{}", "", now, now),
            )
        return self.get_background_job(job_id) or {}

    def get_background_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM background_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        for field in ("payload_json", "progress_json", "result_json"):
            item[field.removesuffix("_json")] = json.loads(item.pop(field) or "{}")
        return item

    def list_background_jobs(self, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        sql = "SELECT * FROM background_jobs"
        args: list[Any] = []
        if status:
            sql += " WHERE status=?"
            args.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(max(1, min(limit, 1000)))
        with self.connect() as db:
            rows = db.execute(sql, tuple(args)).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            for field in ("payload_json", "progress_json", "result_json"):
                item[field.removesuffix("_json")] = json.loads(item.pop(field) or "{}")
            output.append(item)
        return output

    def update_background_job(self, job_id: str, status: str | None = None, progress: dict[str, Any] | None = None,
                              result: dict[str, Any] | None = None, error: str | None = None) -> dict[str, Any] | None:
        updates: dict[str, Any] = {"updated_at": utc_now()}
        if status is not None:
            updates["status"] = status
            if status == "running":
                updates["started_at"] = utc_now()
            if status in {"completed", "failed", "cancelled"}:
                updates["completed_at"] = utc_now()
        if progress is not None:
            updates["progress_json"] = _json(progress)
        if result is not None:
            updates["result_json"] = _json(result)
        if error is not None:
            updates["error_text"] = error[:10000]
        clause = ",".join(f"{key}=?" for key in updates)
        with self.connect() as db:
            db.execute(f"UPDATE background_jobs SET {clause} WHERE id=?", (*updates.values(), job_id))
        return self.get_background_job(job_id)

    def requeue_interrupted_jobs(self) -> int:
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE background_jobs SET status='queued',updated_at=?,error_text='Recovered after application restart' WHERE status='running'",
                (utc_now(),),
            )
        return cursor.rowcount

    # MCP server registry and audit
    def create_mcp_server(self, name: str, transport: str, config: dict[str, Any], allowed_tools: list[str], enabled: bool = True) -> dict[str, Any]:
        server_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute(
                "INSERT INTO mcp_servers(id,name,transport,config_json,allowed_tools_json,tools_json,enabled,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (server_id, name[:120], transport, _json(config), _json(allowed_tools), "[]", 1 if enabled else 0, now, now),
            )
        return self.get_mcp_server(server_id) or {}

    def get_mcp_server(self, server_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM mcp_servers WHERE id=?", (server_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        item["config"] = json.loads(item.pop("config_json") or "{}")
        item["allowed_tools"] = json.loads(item.pop("allowed_tools_json") or "[]")
        item["tools"] = json.loads(item.pop("tools_json") or "[]")
        return item

    def list_mcp_servers(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM mcp_servers ORDER BY updated_at DESC").fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["enabled"] = bool(item["enabled"])
            item["config"] = json.loads(item.pop("config_json") or "{}")
            item["allowed_tools"] = json.loads(item.pop("allowed_tools_json") or "[]")
            item["tools"] = json.loads(item.pop("tools_json") or "[]")
            output.append(item)
        return output

    def update_mcp_server(self, server_id: str, *, name: str | None = None, allowed_tools: list[str] | None = None, enabled: bool | None = None) -> dict[str, Any] | None:
        updates: dict[str, Any] = {"updated_at": utc_now()}
        if name is not None:
            updates["name"] = name[:120]
        if allowed_tools is not None:
            updates["allowed_tools_json"] = _json([str(item)[:200] for item in allowed_tools[:500]])
        if enabled is not None:
            updates["enabled"] = 1 if enabled else 0
        clause = ",".join(f"{key}=?" for key in updates)
        with self.connect() as db:
            cursor = db.execute(f"UPDATE mcp_servers SET {clause} WHERE id=?", (*updates.values(), server_id))
        if cursor.rowcount == 0:
            return None
        return self.get_mcp_server(server_id)

    def delete_mcp_server(self, server_id: str) -> bool:
        with self.connect() as db:
            db.execute("DELETE FROM mcp_calls WHERE server_id=?", (server_id,))
            cursor = db.execute("DELETE FROM mcp_servers WHERE id=?", (server_id,))
        return cursor.rowcount > 0

    def cache_mcp_tools(self, server_id: str, tools: list[dict[str, Any]]) -> None:
        with self.connect() as db:
            db.execute("UPDATE mcp_servers SET tools_json=?,updated_at=? WHERE id=?", (_json(tools), utc_now(), server_id))

    def record_mcp_call(self, server_id: str, tool_name: str, arguments: dict[str, Any], result: dict[str, Any], ok: bool) -> dict[str, Any]:
        call_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute(
                "INSERT INTO mcp_calls(id,server_id,tool_name,arguments_json,result_json,ok,created_at) VALUES (?,?,?,?,?,?,?)",
                (call_id, server_id, tool_name[:200], _json(arguments), _json(result), 1 if ok else 0, utc_now()),
            )
        return {"id": call_id, "server_id": server_id, "tool_name": tool_name, "ok": ok}