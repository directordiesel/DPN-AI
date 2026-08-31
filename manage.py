from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from app.config import settings
from app.database_maintenance import DatabaseMaintenance
from app.db import Database
from app.model_gateway import ModelGateway
from app.tools.registry import ToolRegistry


def stack() -> tuple[Database, ToolRegistry, ModelGateway]:
    db = Database(settings.database_path)
    tools = ToolRegistry(settings, db)
    gateway = ModelGateway(settings, db, tools.vault)
    tools.ollama = gateway
    tools.semantic.ollama = gateway
    return db, tools, gateway


def database_maintenance() -> DatabaseMaintenance:
    return DatabaseMaintenance(settings.database_path, settings.data_dir / "database_backups")


async def doctor() -> dict[str, Any]:
    db, tools, gateway = stack()
    result = tools.diagnostics.report()
    result["model_gateway"] = await gateway.health()
    result["ollama"] = result["model_gateway"].get("ollama", {})
    try:
        result["models"] = await gateway.list_models()
    except Exception as exc:  # noqa: BLE001
        result["models"] = []
        result["model_error"] = str(exc)
    try:
        maintenance = database_maintenance()
        result["database"] = maintenance.integrity_check(full=False)
        maintenance.harden_permissions()
    except Exception as exc:  # noqa: BLE001
        result["database"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    result["universal_core"] = {
        "tools": len(tools.schemas()),
        "plugin_errors": tools.plugin_errors,
        "missions": len(db.list_missions(limit=1000)),
        "pending_approvals": len(db.list_approvals("pending", 1000)),
        "skills": len(tools.skills.list().get("skills", [])),
        "connectors": len(db.list_connectors()),
        "workflows": len(db.list_workflows()),
        "browser": tools.browser.status(),
        "desktop": tools.desktop.status(),
        "voice": tools.voice.status(),
        "media": tools.media.status(),
        "cognitive_kernel": {"goal_contracts": True, "evidence_verification": True},
        "knowledge_graph": tools.graph.stats(),
        "sandbox": tools.sandbox.status(),
        "mcp": {**tools.mcp.status(), "servers": len(db.list_mcp_servers())},
        "capability_forge": tools.forge.list(),
        "background_jobs": {"total": len(db.list_background_jobs(limit=1000))},
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="DPN AI v5 local management console")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Run local system and service diagnostics")
    backup = sub.add_parser("backup", help="Create a verified workspace snapshot")
    backup.add_argument("--name", default="manual-cli-backup")
    backup.add_argument("--path", default=".")
    db_check = sub.add_parser("db-check", help="Run a SQLite database integrity check")
    db_check.add_argument("--full", action="store_true", help="Run the slower full integrity_check")
    db_backup = sub.add_parser("db-backup", help="Create an atomic verified SQLite backup")
    db_backup.add_argument("--name", default=None)
    db_verify = sub.add_parser("db-verify", help="Verify a database backup from the private backup directory")
    db_verify.add_argument("name")
    index = sub.add_parser("index", help="Index workspace knowledge")
    index.add_argument("--force", action="store_true")
    sub.add_parser("projects", help="List persistent projects and task counts")
    sub.add_parser("automations", help="List scheduled local automations")
    sub.add_parser("missions", help="List universal missions")
    sub.add_parser("approvals", help="List pending approval requests")
    sub.add_parser("skills", help="List installed skill packs")
    sub.add_parser("workflows", help="List reusable workflows")
    jobs = sub.add_parser("jobs", help="List persistent autonomous jobs")
    jobs.add_argument("--status", default=None)
    sub.add_parser("graph", help="Show provenance knowledge graph statistics")
    sub.add_parser("mcp", help="Show configured MCP servers with secrets redacted")
    sub.add_parser("capabilities", help="List active, staged, and backed-up capability plugins")
    voices = sub.add_parser("install-voices", help="Install local DPN Sentinel and DPN Aurora neural voices")
    voices.add_argument("voice_ids", nargs="*", default=["sentinel", "aurora"])
    secret = sub.add_parser("set-secret", help="Read a secret from stdin and save it encrypted")
    secret.add_argument("name")
    args = parser.parse_args()

    if args.command in {"db-check", "db-backup", "db-verify"}:
        maintenance = database_maintenance()
        try:
            maintenance.harden_permissions()
            if args.command == "db-check":
                output = maintenance.integrity_check(full=args.full)
            elif args.command == "db-backup":
                output = maintenance.backup(args.name)
            else:
                output = maintenance.verify_backup(args.name)
        except Exception as exc:  # noqa: BLE001
            output = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(output, indent=2, ensure_ascii=False, default=str))
        return 0 if output.get("ok", False) else 1

    db, tools, _ = stack()
    if args.command == "doctor":
        output = asyncio.run(doctor())
    elif args.command == "backup":
        output = tools.snapshots.create(args.name, args.path)
    elif args.command == "index":
        output = tools.knowledge.index_workspace(".", force=args.force)
    elif args.command == "projects":
        output = {"projects": db.list_projects(include_archived=True)}
    elif args.command == "automations":
        output = {"automations": db.list_automations()}
    elif args.command == "missions":
        output = {"missions": db.list_missions(limit=1000)}
    elif args.command == "approvals":
        output = {"approvals": db.list_approvals("pending", 1000)}
    elif args.command == "skills":
        output = tools.skills.list()
    elif args.command == "workflows":
        output = {"workflows": db.list_workflows()}
    elif args.command == "jobs":
        output = {"jobs": db.list_background_jobs(args.status, 1000)}
    elif args.command == "graph":
        output = tools.graph.stats()
    elif args.command == "mcp":
        output = tools.mcp.list_servers()
    elif args.command == "capabilities":
        output = tools.forge.list()
    elif args.command == "install-voices":
        results = [tools.voice.install_profile(voice_id) for voice_id in args.voice_ids]
        output = {"ok": all(item.get("ok") for item in results), "voices": results}
    elif args.command == "set-secret":
        value = sys.stdin.read().rstrip("\r\n")
        output = tools.vault.set(args.name, value) if value else {"ok": False, "error": "No secret value received on stdin"}
    else:
        parser.error("Unknown command")
        return 2
    print(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    return 0 if output.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
