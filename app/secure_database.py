from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.db import Database, utc_now
from app.persistence_security import sanitize_for_persistence


class SecureDatabase(Database):
    """Production database boundary with fail-closed path and persistence controls.

    The legacy Database class remains the schema/API implementation. This
    subclass hardens the runtime boundary without duplicating the large schema
    definition: explicit rollback, symlink rejection, private SQLite files, and
    centralized sanitization for diagnostic/event persistence.
    """

    @staticmethod
    def _reject_symlink_components(path: Path) -> None:
        absolute = Path(os.path.abspath(path))
        current = Path(absolute.anchor)
        for part in absolute.parts[1:]:
            current = current / part
            if current.exists() and current.is_symlink():
                raise ValueError(f"Symlinked database path component is not allowed: {current}")

    @classmethod
    def _validate_database_path(cls, path: Path) -> None:
        cls._reject_symlink_components(path.parent)
        if path.exists() and path.is_symlink():
            raise ValueError("Database file must not be a symlink")
        if path.exists() and not path.is_file():
            raise ValueError("Database path must be a regular file")

    @staticmethod
    def _private_file(path: Path) -> None:
        if os.name == "posix" and path.exists() and not path.is_symlink():
            try:
                path.chmod(0o600)
            except OSError:
                pass

    def _harden_sqlite_files(self) -> None:
        for candidate in (self.path, Path(f"{self.path}-wal"), Path(f"{self.path}-shm")):
            self._private_file(candidate)

    def __init__(self, path: Path):
        path = Path(path)
        self._validate_database_path(path)
        super().__init__(path)
        self._harden_sqlite_files()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self._validate_database_path(self.path)
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA trusted_schema=OFF")
        try:
            yield connection
            connection.commit()
        except BaseException:
            try:
                connection.rollback()
            finally:
                raise
        finally:
            connection.close()
            self._harden_sqlite_files()

    @staticmethod
    def _safe_text(value: Any, limit: int = 20_000) -> str:
        return str(sanitize_for_persistence(value))[:limit]

    @staticmethod
    def _safe_json(value: Any) -> str:
        return json.dumps(sanitize_for_persistence(value), ensure_ascii=False, default=str)

    def audit(self, event_type: str, summary: str, metadata: dict[str, Any] | None = None,
              actor: str = "system") -> None:
        safe_summary = self._safe_text(summary, 8_000)
        safe_metadata = sanitize_for_persistence(metadata or {})
        with self.connect() as db:
            db.execute(
                "INSERT INTO audit_events(event_type,actor,summary,metadata_json,created_at) VALUES (?,?,?,?,?)",
                (str(event_type)[:200], str(actor)[:200], safe_summary, json.dumps(safe_metadata, ensure_ascii=False, default=str), utc_now()),
            )

    def finish_run(self, run_id: str, status: str, traces: list[dict[str, Any]],
                   result_text: str = "", error_text: str = "") -> None:
        safe_traces = sanitize_for_persistence(traces)
        safe_result = self._safe_text(result_text, 100_000)
        safe_error = self._safe_text(error_text, 20_000)
        with self.connect() as db:
            db.execute(
                "UPDATE operation_runs SET status=?, trace_json=?, result_text=?, error_text=?, completed_at=? WHERE id=?",
                (
                    str(status)[:40],
                    json.dumps(safe_traces, ensure_ascii=False, default=str),
                    safe_result,
                    safe_error,
                    utc_now(),
                    run_id,
                ),
            )
        self.audit("run.finished", f"Operation {status}", {"run_id": run_id, "trace_count": len(traces)})

    def create_workflow_run(self, workflow_id: str, inputs: dict[str, Any]) -> str:
        run_id = str(uuid.uuid4())
        safe_inputs = sanitize_for_persistence(inputs)
        with self.connect() as db:
            db.execute(
                "INSERT INTO workflow_runs(id,workflow_id,status,inputs_json,outputs_json,error_text,created_at) VALUES (?,?,?,?,?,?,?)",
                (run_id, workflow_id, "running", json.dumps(safe_inputs, ensure_ascii=False, default=str), "{}", "", utc_now()),
            )
        return run_id

    def finish_workflow_run(self, run_id: str, status: str, outputs: dict[str, Any] | None = None,
                            error: str = "") -> None:
        safe_outputs = sanitize_for_persistence(outputs or {})
        safe_error = self._safe_text(error, 20_000)
        with self.connect() as db:
            db.execute(
                "UPDATE workflow_runs SET status=?,outputs_json=?,error_text=?,completed_at=? WHERE id=?",
                (
                    str(status)[:40],
                    json.dumps(safe_outputs, ensure_ascii=False, default=str),
                    safe_error,
                    utc_now(),
                    run_id,
                ),
            )

    def add_webhook_event(self, topic: str, payload: dict[str, Any]) -> dict[str, Any]:
        event_id = str(uuid.uuid4())
        safe_payload = sanitize_for_persistence(payload)
        with self.connect() as db:
            db.execute(
                "INSERT INTO webhook_events(id,topic,payload_json,processed,created_at) VALUES (?,?,?,?,?)",
                (event_id, str(topic)[:300], json.dumps(safe_payload, ensure_ascii=False, default=str), 0, utc_now()),
            )
        return {"id": event_id, "topic": str(topic)[:300], "payload": safe_payload, "processed": False}

    def update_background_job(self, job_id: str, status: str | None = None,
                              progress: dict[str, Any] | None = None,
                              result: dict[str, Any] | None = None,
                              error: str | None = None) -> dict[str, Any] | None:
        return super().update_background_job(
            job_id,
            status=status,
            progress=sanitize_for_persistence(progress) if progress is not None else None,
            result=sanitize_for_persistence(result) if result is not None else None,
            error=self._safe_text(error, 10_000) if error is not None else None,
        )

    def resolve_approval(self, approval_id: str, status: str,
                         result: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return super().resolve_approval(
            approval_id,
            status,
            sanitize_for_persistence(result) if result is not None else None,
        )

    def cache_mcp_tools(self, server_id: str, tools: list[dict[str, Any]]) -> None:
        safe_tools = sanitize_for_persistence(tools)
        with self.connect() as db:
            db.execute(
                "UPDATE mcp_servers SET tools_json=?,updated_at=? WHERE id=?",
                (json.dumps(safe_tools, ensure_ascii=False, default=str), utc_now(), server_id),
            )

    def record_mcp_call(self, server_id: str, tool_name: str, arguments: dict[str, Any],
                        result: dict[str, Any], ok: bool) -> dict[str, Any]:
        return super().record_mcp_call(
            server_id,
            tool_name,
            sanitize_for_persistence(arguments),
            sanitize_for_persistence(result),
            ok,
        )
