from __future__ import annotations

import asyncio
import json
import mimetypes
import traceback
import uuid
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.agent import DPNAIAgent
from app.artifact_builder import detect_artifact_intent
from app.automation import AutomationEngine
from app.config import BASE_DIR, settings
from app.db import Database
from app.model_gateway import ModelGateway
from app.job_supervisor import JobSupervisor
from app.ollama_client import OllamaError
from app.orchestrator import MissionOrchestrator
from app.workflows import WorkflowEngine
from app.profiles import list_profiles
from app.schemas import (
    AutomationCreate,
    AutomationPatch,
    ChatRequest,
    ConversationCreate,
    ConversationRename,
    MemoryCreate,
    ProjectCreate,
    ProjectPatch,
    PullModelRequest,
    SettingsPatch,
    SnapshotCreate,
    TaskCreate,
    TaskPatch,
    ApprovalDecision,
    ConnectorCreate,
    MissionCreate,
    SecretCreate,
    SemanticCreate,
    SkillCreate,
    WorkflowCreate,
    WorkflowRunRequest,
    VoiceSynthesisRequest,
    BackgroundJobCreate,
    MCPServerCreate,
    MCPServerPatch,
    GraphNodeCreate,
    GraphEdgeCreate,
    GraphFactCreate,
    CapabilityStageRequest,
    SandboxPythonRequest,
)
from app.services import ExportService
from app.tools.registry import ToolRegistry


APP_VERSION = "6.0.0"
db = Database(settings.database_path)
tools = ToolRegistry(settings, db)
ollama = ModelGateway(settings, db, tools.vault)
tools.ollama = ollama
tools.semantic.ollama = ollama
agent = DPNAIAgent(settings, db, ollama, tools)
exports = ExportService(settings, db)
automation_engine = AutomationEngine(db, agent)
orchestrator = MissionOrchestrator(settings, db, ollama, agent)
workflow_engine = WorkflowEngine(db, agent, tools)
job_supervisor = JobSupervisor(db, agent, orchestrator, workflow_engine, settings.max_parallel_jobs)


def _seed_builtin_workflows() -> None:
    existing = {item["name"] for item in db.list_workflows()}
    definitions = [
        (
            "Workspace Intelligence Scan",
            "Map the restricted workspace, collect diagnostics, and refresh the local knowledge index.",
            [
                {"id": "tree", "type": "tool", "tool": "directory_tree", "arguments": {"path": ".", "max_depth": 5, "max_entries": 1000}},
                {"id": "diagnostics", "type": "tool", "tool": "system_diagnostics", "arguments": {}},
                {"id": "index", "type": "tool", "tool": "index_workspace", "arguments": {"path": ".", "force": False, "max_files": 2000}},
            ],
        ),
        (
            "Verified Software Release",
            "Snapshot, inspect, repair, test, review, and package a software project.",
            [
                {"id": "snapshot", "type": "tool", "tool": "create_workspace_snapshot", "arguments": {"name": "workflow-pre-release", "path": "."}},
                {"id": "engineer", "type": "prompt", "profile": "software", "prompt": "Inspect the workspace project. Repair defects, improve reliability and security, run every available validation, and package a release with exact evidence. User objective: {{inputs.objective}}"},
                {"id": "verify", "type": "prompt", "profile": "security", "prompt": "Independently verify the current workspace release against this objective: {{inputs.objective}}. Inspect evidence, run safe checks, and report pass, partial, or fail."},
            ],
        ),
        (
            "Business Automation Delivery Pack",
            "Create a client-ready automation offer, implementation plan, ROI model, SOP, and presentation.",
            [
                {"id": "strategy", "type": "prompt", "profile": "business", "prompt": "Design a complete business automation solution for: {{inputs.business_problem}}. Define discovery questions, workflow, exceptions, measurable ROI, scope, pricing, implementation, security, and support."},
                {"id": "documents", "type": "prompt", "profile": "documents", "prompt": "Using the business strategy created in this workflow, generate the client-ready Word proposal, PDF overview, Excel ROI/pricing workbook, and PowerPoint pitch under workspace/generated."},
            ],
        ),
        (
            "Voice Assistant Readiness",
            "Check local speech, voice packs, model routing, and media prerequisites before a hands-free session.",
            [
                {"id": "voice", "type": "tool", "tool": "voice_status", "arguments": {}},
                {"id": "profiles", "type": "tool", "tool": "list_voice_profiles", "arguments": {}},
                {"id": "media", "type": "tool", "tool": "media_status", "arguments": {}},
                {"id": "diagnostics", "type": "tool", "tool": "system_diagnostics", "arguments": {}},
            ],
        ),
        (
            "Universal Capability Readiness",
            "Inspect model, sandbox, MCP, graph memory, desktop, voice, and extension readiness before a broad autonomous mission.",
            [
                {"id": "diagnostics", "type": "tool", "tool": "system_diagnostics", "arguments": {}},
                {"id": "sandbox", "type": "tool", "tool": "sandbox_status", "arguments": {}},
                {"id": "mcp", "type": "tool", "tool": "mcp_status", "arguments": {}},
                {"id": "graph", "type": "tool", "tool": "graph_stats", "arguments": {}},
                {"id": "capabilities", "type": "tool", "tool": "list_capabilities", "arguments": {}},
                {"id": "desktop", "type": "tool", "tool": "desktop_status", "arguments": {}},
                {"id": "voice", "type": "tool", "tool": "voice_status", "arguments": {}},
            ],
        ),
        (
            "Evidence-Driven Universal Mission",
            "Create a goal contract, execute a mission with checkpoints, repair failures, and require a review quorum.",
            [
                {"id": "contract", "type": "tool", "tool": "analyze_goal", "arguments": {"objective": "{{inputs.objective}}"}},
                {"id": "mission", "type": "prompt", "profile": "director", "prompt": "Execute this objective as a complete evidence-driven operation. Establish acceptance criteria, use focused tools, preserve checkpoints, validate outputs, repair defects, and report exact evidence: {{inputs.objective}}"},
                {"id": "verify", "type": "prompt", "profile": "security", "prompt": "Independently inspect and verify the outputs for this objective. Do not accept unsupported claims: {{inputs.objective}}"},
            ],
        ),
    ]
    for name, description, steps in definitions:
        if name not in existing:
            db.create_workflow(name, description, steps)


_seed_builtin_workflows()


async def _intelligence_keeper() -> None:
    """Keep the strongest available local model resident without blocking startup."""
    while True:
        try:
            effective = agent.effective_settings()
            if effective.get("keep_model_loaded", True):
                result = await ollama.warm_best_model(str(effective.get("model") or settings.default_model))
                db.set_setting("active_intelligence_model", result.get("model"))
                db.set_setting("intelligence_warm_status", {"ok": True, **result})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            db.set_setting("intelligence_warm_status", {"ok": False, "error": str(exc)[:1000]})
        await asyncio.sleep(900)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await automation_engine.start()
    await job_supervisor.start()
    keeper_task = asyncio.create_task(_intelligence_keeper(), name="dpn-intelligence-keeper")
    yield
    keeper_task.cancel()
    try:
        await keeper_task
    except asyncio.CancelledError:
        pass
    await job_supervisor.stop()
    await automation_engine.stop()


app = FastAPI(title="DPN AI", version=APP_VERSION, docs_url="/api/docs", redoc_url=None, lifespan=lifespan)


def _write_server_error(error_id: str, request: Request, exc: Exception) -> None:
    log_dir = BASE_DIR / "runtime_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "errors.log"
    stamp = datetime.now(timezone.utc).isoformat()
    entry = (
        f"\n[{stamp}] ERROR {error_id} {request.method} {request.url.path}\n"
        f"{type(exc).__name__}: {exc}\n"
        f"{''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))}\n"
    )
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(entry)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    error_id = uuid.uuid4().hex[:10].upper()
    try:
        _write_server_error(error_id, request, exc)
    except Exception:
        pass
    detail = (
        f"DPN AI encountered {type(exc).__name__}: {str(exc)[:500] or 'No details were returned'}. "
        f"Error ID {error_id}. See runtime_logs\\errors.log."
    )
    return JSONResponse(status_code=500, content={"detail": detail, "error_id": error_id})


@app.middleware("http")
async def local_access_boundary(request: Request, call_next):
    if request.url.path.startswith("/api"):
        client_host = request.client.host if request.client else ""
        is_loopback = client_host in {"127.0.0.1", "::1", "localhost", "testclient"}
        supplied = request.headers.get("X-DPN-Token", "")
        if settings.access_token:
            if supplied != settings.access_token:
                return JSONResponse(status_code=401, content={"detail": "A valid X-DPN-Token is required."})
        elif not is_loopback:
            return JSONResponse(status_code=503, content={"detail": "Remote API access is disabled until DPN_ACCESS_TOKEN is configured."})
    return await call_next(request)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    ollama_status = await ollama.health()
    projects = db.list_projects()
    automations = db.list_automations()
    return {
        "app": "DPN AI",
        "version": APP_VERSION,
        "ollama": ollama_status,
        "model_gateway": ollama_status,
        "workspace": tools.fs.disk_summary(),
        "knowledge": tools.knowledge.stats(),
        "projects": {"total": len(projects), "active": sum(item["status"] == "active" for item in projects)},
        "automations": {"total": len(automations), "enabled": sum(item["enabled"] for item in automations)},
        "plugins": {"loaded_tools": len(tools.schemas()), "errors": tools.plugin_errors},
        "universal_core": {
            "missions": len(db.list_missions(limit=1000)),
            "pending_approvals": len(db.list_approvals("pending", 1000)),
            "skills": len(tools.skills.list().get("skills", [])),
            "connectors": len(db.list_connectors()),
            "workflows": len(db.list_workflows()),
            "browser": tools.browser.status(),
            "desktop": tools.desktop.status(),
            "voice": tools.voice.diagnostics(),
            "media": tools.media.status(),
            "cognitive_kernel": {"goal_contracts": True, "evidence_verification": True, "review_quorum": settings.review_quorum},
            "knowledge_graph": tools.graph.stats(),
            "sandbox": tools.sandbox.status(),
            "mcp": {**tools.mcp.status(), "servers": len(db.list_mcp_servers())},
            "capability_forge": tools.forge.list(),
            "background_jobs": {"total": len(db.list_background_jobs(limit=1000)), "running": len(db.list_background_jobs("running", 1000)), "queued": len(db.list_background_jobs("queued", 1000))},
        },
        "image_generation": {"comfyui_url": settings.comfyui_url, "workflow_configured": settings.comfyui_workflow_path.exists()},
        "intelligence": {
            "mode": agent.effective_settings().get("intelligence_mode", "maximum"),
            "active_model": db.get_setting("active_intelligence_model", "warming"),
            "warm_status": db.get_setting("intelligence_warm_status", {"ok": False, "status": "starting"}),
        },
        "settings": agent.effective_settings(),
    }


@app.get("/api/profiles")
def profiles() -> dict[str, Any]:
    return {"profiles": list_profiles()}


@app.get("/api/tools")
def tool_catalog() -> dict[str, Any]:
    return {"tools": tools.catalog(), "count": len(tools.catalog())}


@app.get("/api/models")
async def list_models() -> dict[str, Any]:
    try:
        return {"models": await ollama.list_models()}
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/models/warm")
async def warm_model() -> dict[str, Any]:
    try:
        effective = agent.effective_settings()
        result = await ollama.warm_best_model(str(effective.get("model") or settings.default_model))
        db.set_setting("active_intelligence_model", result.get("model"))
        db.set_setting("intelligence_warm_status", {"ok": True, **result})
        return result
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/models/pull")
async def pull_model(request: PullModelRequest) -> dict[str, Any]:
    try:
        return await ollama.pull_model(request.model)
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return agent.effective_settings()


@app.patch("/api/settings")
def patch_settings(request: SettingsPatch) -> dict[str, Any]:
    values = request.model_dump(exclude_none=True)
    for key, value in values.items():
        db.set_setting(key, value)
    if "command_timeout_seconds" in values:
        tools.shell.timeout_seconds = int(values["command_timeout_seconds"])
    if "allow_host_sandbox" in values:
        tools.sandbox.allow_host_fallback = bool(values["allow_host_sandbox"])
    db.audit("settings.updated", "Updated DPN AI settings", {"keys": sorted(values)})
    return agent.effective_settings()


@app.get("/api/conversations")
def list_conversations() -> dict[str, Any]:
    return {"conversations": db.list_conversations()}


@app.post("/api/conversations")
def create_conversation(request: ConversationCreate) -> dict[str, str]:
    return {"id": db.create_conversation(request.title)}


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str) -> dict[str, Any]:
    messages = db.get_messages(conversation_id, limit=1000)
    if not messages and not any(item["id"] == conversation_id for item in db.list_conversations(limit=10000)):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"id": conversation_id, "messages": messages}


@app.patch("/api/conversations/{conversation_id}")
def rename_conversation(conversation_id: str, request: ConversationRename) -> dict[str, Any]:
    if not db.rename_conversation(conversation_id, request.title):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"ok": True, "title": request.title}


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict[str, bool]:
    return {"deleted": db.delete_conversation(conversation_id)}


@app.post("/api/conversations/{conversation_id}/export")
def export_conversation(conversation_id: str, format: str = "markdown") -> dict[str, Any]:
    if format not in {"markdown", "json"}:
        raise HTTPException(status_code=400, detail="Format must be markdown or json")
    result = exports.conversation(conversation_id, format)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@app.post("/api/chat")
async def chat(request: ChatRequest) -> Any:
    try:
        use_mission = request.execution_mode == "mission" or (
            request.execution_mode == "auto" and request.edit_message_id is None
            and agent.should_use_mission(request.message, request.attachments, request.profile)
        )
        if use_mission:
            return await orchestrator.run(
                objective=request.message,
                conversation_id=request.conversation_id,
                project_id=request.project_id,
                attachments=request.attachments,
                profile=request.profile,
                model=request.model,
                think=request.think,
                budget=request.budget,
            )
        response = await agent.run(
            conversation_id=request.conversation_id,
            user_message=request.message,
            model=request.model,
            think=request.think,
            attachments=request.attachments,
            profile=request.profile,
            project_id=request.project_id,
            skill_ids=request.skill_ids,
            edit_message_id=request.edit_message_id,
        )
        artifact_expected = bool(detect_artifact_intent(request.message).kinds)
        should_verify = request.verify and agent.should_verify(
            request.message, request.attachments, request.profile, artifact_expected
        )
        if should_verify:
            review_contract = tools.cognitive.derive_contract(request.message)
            review = await orchestrator.review(review_contract, [{"message": response.message, "generated_files": response.generated_files,
                                                                   "tool_count": len(response.traces)}],
                                               (request.model if request.model not in {None, "", "__maximum__", "auto", "auto:max"} else None)
                                               or agent.effective_settings().get("reviewer_model") or response.model,
                                               request.think if request.think is not None else agent.effective_settings()["think_level"])
            payload = response.model_dump()
            payload["verification"] = review
            return payload
        return response
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest, http_request: Request) -> StreamingResponse:
    """Stream progress and ordinary chat tokens as newline-delimited JSON events."""
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def emit(event: dict[str, Any]) -> None:
        await queue.put(event)

    async def worker() -> None:
        try:
            use_mission = request.execution_mode == "mission" or (
                request.execution_mode == "auto" and request.edit_message_id is None
                and agent.should_use_mission(request.message, request.attachments, request.profile)
            )
            if use_mission:
                await emit({"type": "status", "stage": "mission", "message": "Building and executing a verified specialist mission"})
                payload: Any = await orchestrator.run(
                    objective=request.message,
                    conversation_id=request.conversation_id,
                    project_id=request.project_id,
                    attachments=request.attachments,
                    profile=request.profile,
                    model=request.model,
                    think=request.think,
                    budget=request.budget,
                )
            else:
                response = await agent.run(
                    conversation_id=request.conversation_id,
                    user_message=request.message,
                    model=request.model,
                    think=request.think,
                    attachments=request.attachments,
                    profile=request.profile,
                    project_id=request.project_id,
                    skill_ids=request.skill_ids,
                    edit_message_id=request.edit_message_id,
                    event_callback=emit,
                )
                payload = response.model_dump()
                artifact_expected = bool(detect_artifact_intent(request.message).kinds)
                should_verify = request.verify and agent.should_verify(
                    request.message, request.attachments, request.profile, artifact_expected
                )
                if should_verify:
                    await emit({"type": "status", "stage": "verify", "message": "Independently verifying the completed work"})
                    review_contract = tools.cognitive.derive_contract(request.message)
                    review = await orchestrator.review(
                        review_contract,
                        [{"message": response.message, "generated_files": response.generated_files, "tool_count": len(response.traces)}],
                        (request.model if request.model not in {None, "", "__maximum__", "auto", "auto:max"} else None)
                        or agent.effective_settings().get("reviewer_model") or response.model,
                        request.think if request.think is not None else agent.effective_settings()["think_level"],
                    )
                    payload["verification"] = review
            await emit({"type": "final", "data": payload})
        except (OllamaError, ValueError) as exc:
            await emit({"type": "error", "message": str(exc), "error_type": type(exc).__name__})
        except Exception as exc:  # noqa: BLE001
            error_id = uuid.uuid4().hex[:10].upper()
            try:
                _write_server_error(error_id, http_request, exc)
            except Exception:
                pass
            await emit({
                "type": "error",
                "message": f"DPN AI encountered {type(exc).__name__}: {str(exc)[:500]}. Error ID {error_id}. See runtime_logs\\errors.log.",
                "error_id": error_id,
            })
        finally:
            await queue.put(None)

    asyncio.create_task(worker(), name="dpn-chat-stream")

    async def events():
        while True:
            item = await queue.get()
            if item is None:
                break
            yield json.dumps(item, ensure_ascii=False, default=str) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache"})


# DPN AI v5 local conversational voice console
@app.get("/api/voice/status")
def voice_status() -> dict[str, Any]:
    return tools.voice.diagnostics()


@app.get("/api/voice/profiles")
def voice_profiles() -> dict[str, Any]:
    return tools.voice.profiles()


@app.post("/api/voice/profiles/{voice_id}/install")
async def install_voice_profile(voice_id: str) -> dict[str, Any]:
    if not agent.effective_settings()["allow_voice"]:
        raise HTTPException(status_code=403, detail="Voice capabilities are disabled in Settings")
    result = await asyncio.to_thread(tools.voice.install_profile, voice_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    db.audit("voice.installed", f"Installed voice profile {voice_id}")
    return result


@app.post("/api/voice/transcribe")
async def transcribe_voice(
    file: UploadFile = File(...),
    model_size: str = Form("base"),
    language: str | None = Form(None),
    initial_prompt: str | None = Form(None),
) -> dict[str, Any]:
    if not agent.effective_settings()["allow_voice"]:
        raise HTTPException(status_code=403, detail="Voice capabilities are disabled in Settings")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The recording is empty")
    if len(data) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Voice recording exceeds 100 MB")
    path = tools.voice.save_upload(data, file.filename or "recording.webm")
    result = await asyncio.to_thread(tools.voice.transcribe, path, model_size, language, initial_prompt)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    db.audit("voice.transcribed", "Transcribed a local microphone recording", {"path": path, "model": model_size})
    return result


@app.post("/api/voice/synthesize")
async def synthesize_voice(request: VoiceSynthesisRequest) -> dict[str, Any]:
    if not agent.effective_settings()["allow_voice"]:
        raise HTTPException(status_code=403, detail="Voice capabilities are disabled in Settings")
    result = await asyncio.to_thread(
        tools.voice.speak,
        request.text,
        request.filename,
        175,
        request.voice_id,
        request.speed,
        request.volume,
        request.use_cuda,
        True,
        request.tone,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    result["download_url"] = f"/api/files/download/{result['path']}"
    db.audit("voice.synthesized", f"Synthesized speech with {request.voice_id}", {"path": result["path"], "characters": result["characters"]})
    return result


@app.post("/api/voice/cache/clear")
def clear_voice_cache() -> dict[str, Any]:
    return tools.voice.clear_caches()


@app.get("/api/capabilities")
async def capability_manifest() -> dict[str, Any]:
    return {
        "version": APP_VERSION,
        "models": await ollama.health(),
        "voice": tools.voice.diagnostics(),
        "media": tools.media.status(),
        "browser": tools.browser.status(),
        "desktop": tools.desktop.status(),
        "images": {"comfyui_url": settings.comfyui_url, "workflow_configured": settings.comfyui_workflow_path.exists()},
        "tools": tools.catalog(),
        "profiles": list_profiles(),
        "limits": {
            "agent_steps": settings.max_agent_steps,
            "mission_steps": settings.max_mission_steps,
            "tool_calls": agent.effective_settings()["max_tool_calls"],
            "runtime_seconds": agent.effective_settings()["max_run_seconds"],
        },
    }


@app.get("/api/memories")
def list_memories() -> dict[str, Any]:
    return {"memories": db.list_memories()}


@app.post("/api/memories")
def add_memory(request: MemoryCreate) -> dict[str, bool]:
    db.upsert_memory(request.key, request.value)
    db.audit("memory.saved", f"Saved memory {request.key}")
    return {"ok": True}


@app.delete("/api/memories/{key}")
def delete_memory(key: str) -> dict[str, bool]:
    return {"deleted": db.delete_memory(key)}


# Projects and task board
@app.get("/api/projects")
def list_projects(include_archived: bool = False) -> dict[str, Any]:
    return {"projects": db.list_projects(include_archived)}


@app.post("/api/projects")
def create_project(request: ProjectCreate) -> dict[str, Any]:
    try:
        tools.fs.resolve(request.root_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"project": db.create_project(request.name, request.description, request.root_path)}


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": project, "tasks": db.list_tasks(project_id), "runs": db.list_runs(50, project_id)}


@app.patch("/api/projects/{project_id}")
def patch_project(project_id: str, request: ProjectPatch) -> dict[str, Any]:
    values = request.model_dump(exclude_none=True)
    if "root_path" in values:
        try:
            tools.fs.resolve(values["root_path"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    project = db.update_project(project_id, values)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": project}


@app.get("/api/projects/{project_id}/tasks")
def list_project_tasks(project_id: str, status: str | None = None) -> dict[str, Any]:
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"tasks": db.list_tasks(project_id, status)}


@app.post("/api/projects/{project_id}/tasks")
def create_project_task(project_id: str, request: TaskCreate) -> dict[str, Any]:
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"task": db.create_task(project_id, request.title, request.details, request.priority, request.dependencies)}


@app.patch("/api/tasks/{task_id}")
def patch_task(task_id: str, request: TaskPatch) -> dict[str, Any]:
    task = db.update_task(task_id, request.model_dump(exclude_none=True))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task": task}


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str) -> dict[str, bool]:
    return {"deleted": db.delete_task(task_id)}


# Runs, audit, diagnostics
@app.get("/api/runs")
def list_runs(limit: int = 100, project_id: str | None = None) -> dict[str, Any]:
    return {"runs": db.list_runs(limit, project_id)}


@app.get("/api/audit")
def list_audit(limit: int = 200) -> dict[str, Any]:
    return {"events": db.list_audit(limit)}


@app.get("/api/diagnostics")
async def diagnostics() -> dict[str, Any]:
    report = tools.diagnostics.report()
    report["ollama"] = await ollama.health()
    try:
        report["models"] = await ollama.list_models()
    except OllamaError:
        report["models"] = []
    report["plugins"] = {"errors": tools.plugin_errors, "tool_count": len(tools.schemas())}
    return report


# Snapshots
@app.get("/api/snapshots")
def list_snapshots() -> dict[str, Any]:
    return tools.snapshots.list()


@app.post("/api/snapshots")
def create_snapshot(request: SnapshotCreate) -> dict[str, Any]:
    result = tools.snapshots.create(request.name, request.path)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.post("/api/snapshots/{snapshot_id}/restore")
def restore_snapshot(snapshot_id: str, overwrite: bool = False) -> dict[str, Any]:
    result = tools.snapshots.restore(snapshot_id, overwrite)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    tools.knowledge.index_workspace(".", force=True)
    return result


@app.get("/api/snapshots/{snapshot_id}/download")
def download_snapshot(snapshot_id: str) -> FileResponse:
    snapshot = db.get_snapshot(snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    path = Path(snapshot["archive_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Snapshot archive is missing")
    return FileResponse(path, filename=path.name, media_type="application/zip")


# Local scheduled automations
@app.get("/api/automations")
def list_automations() -> dict[str, Any]:
    return {"automations": db.list_automations()}


@app.post("/api/automations")
def create_automation(request: AutomationCreate) -> dict[str, Any]:
    values = request.model_dump()
    try:
        values["next_run_at"] = automation_engine.validate(request.schedule_type, request.schedule_value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    automation = db.create_automation(values)
    automation = db.update_automation(automation["id"], {"next_run_at": values["next_run_at"]})
    return {"automation": automation}


@app.patch("/api/automations/{automation_id}")
def patch_automation(automation_id: str, request: AutomationPatch) -> dict[str, Any]:
    current = db.get_automation(automation_id)
    if not current:
        raise HTTPException(status_code=404, detail="Automation not found")
    values = request.model_dump(exclude_none=True)
    schedule_type = values.get("schedule_type", current["schedule_type"])
    schedule_value = values.get("schedule_value", current["schedule_value"])
    if "schedule_type" in values or "schedule_value" in values:
        try:
            values["next_run_at"] = automation_engine.validate(schedule_type, schedule_value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"automation": db.update_automation(automation_id, values)}


@app.post("/api/automations/{automation_id}/run")
async def run_automation(automation_id: str) -> dict[str, Any]:
    if not agent.effective_settings()["allow_automations"]:
        raise HTTPException(status_code=403, detail="Automations are disabled in Settings")
    result = await automation_engine.run_now(automation_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.delete("/api/automations/{automation_id}")
def delete_automation(automation_id: str) -> dict[str, bool]:
    return {"deleted": db.delete_automation(automation_id)}



# Universal mission orchestration
@app.get("/api/missions")
def list_missions(limit: int = 100, status: str | None = None) -> dict[str, Any]:
    return {"missions": db.list_missions(limit, status)}


@app.get("/api/missions/{mission_id}")
def get_mission(mission_id: str) -> dict[str, Any]:
    mission = db.get_mission(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    mission["goal_contract"] = db.get_goal_contract(mission_id)
    mission["checkpoints"] = db.list_checkpoints(mission_id)
    mission["evaluations"] = db.list_evaluations(mission_id)
    return {"mission": mission}


@app.post("/api/missions")
async def create_mission(request: MissionCreate) -> dict[str, Any]:
    return await orchestrator.run(
        request.objective, request.conversation_id, request.project_id, request.attachments,
        request.profile, request.model, request.think, request.budget,
    )


# Approval inbox
@app.get("/api/approvals")
def list_approvals(status: str | None = "pending", limit: int = 200) -> dict[str, Any]:
    return {"approvals": db.list_approvals(status, limit)}


@app.post("/api/approvals/{approval_id}/decision")
async def decide_approval(approval_id: str, request: ApprovalDecision) -> dict[str, Any]:
    approval = db.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    resolved = db.resolve_approval(approval_id, request.decision)
    result = None
    if request.decision == "approved":
        result = await tools.execute_approval(approval_id)
    return {"approval": db.get_approval(approval_id) or resolved, "execution": result}


# Skill packs
@app.get("/api/skills")
def list_skills() -> dict[str, Any]:
    return tools.skills.list()


@app.get("/api/skills/{skill_id}")
def get_skill(skill_id: str) -> dict[str, Any]:
    result = tools.skills.get(skill_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@app.post("/api/skills")
def create_skill(request: SkillCreate) -> dict[str, Any]:
    result = tools.skills.create(**request.model_dump())
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    db.audit("skill.created", f"Created skill {request.skill_id}")
    return result


# Semantic memory
@app.post("/api/semantic")
async def add_semantic(request: SemanticCreate) -> dict[str, Any]:
    return await tools.semantic.add(**request.model_dump())


@app.get("/api/semantic/search")
async def search_semantic(q: str, namespace: str = "global", limit: int = 8) -> dict[str, Any]:
    return await tools.semantic.search(q, namespace, limit)


# Encrypted local secrets
@app.get("/api/secrets")
def list_secrets() -> dict[str, Any]:
    return tools.vault.list()


@app.post("/api/secrets")
def set_secret(request: SecretCreate) -> dict[str, Any]:
    result = tools.vault.set(request.name, request.value)
    db.audit("secret.updated", f"Updated encrypted secret {request.name}")
    return result


@app.delete("/api/secrets/{name}")
def delete_secret(name: str) -> dict[str, Any]:
    result = tools.vault.delete(name)
    db.audit("secret.deleted", f"Deleted encrypted secret {name}")
    return result


# Connector hub
@app.get("/api/connectors")
def list_connectors() -> dict[str, Any]:
    return tools.connectors.list()


@app.post("/api/connectors")
def create_connector(request: ConnectorCreate) -> dict[str, Any]:
    result = tools.connectors.create(**request.model_dump())
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    db.audit("connector.created", f"Created connector {request.name}")
    return result


@app.delete("/api/connectors/{connector_id}")
def delete_connector(connector_id: str) -> dict[str, Any]:
    return {"deleted": db.delete_connector(connector_id)}


# Reusable workflows
@app.get("/api/workflows")
def list_workflows() -> dict[str, Any]:
    return {"workflows": db.list_workflows()}


@app.post("/api/workflows")
def create_workflow(request: WorkflowCreate) -> dict[str, Any]:
    return {"workflow": db.create_workflow(request.name, request.description, request.steps, request.enabled)}


@app.post("/api/workflows/{workflow_id}/run")
async def run_workflow(workflow_id: str, request: WorkflowRunRequest) -> dict[str, Any]:
    effective = agent.effective_settings()
    permissions = {
        "allow_commands": effective["allow_commands"], "allow_web": effective["allow_web"],
        "allow_images": effective["allow_images"], "allow_browser": effective["allow_browser"],
        "allow_desktop": effective["allow_desktop"], "allow_voice": effective["allow_voice"],
        "allow_connectors": effective["allow_connectors"], "approval_mode": effective["approval_mode"],
    }
    return await workflow_engine.run(workflow_id, request.inputs, permissions)


# Incoming local event/webhook inbox. Bind to localhost unless the operator deliberately changes DPN_HOST.
@app.post("/api/events/{topic}")
def receive_event(topic: str, payload: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(payload, default=str)) > 1_000_000:
        raise HTTPException(status_code=413, detail="Event payload exceeds 1 MB")
    event = db.add_webhook_event(topic[:120], payload)
    db.audit("event.received", f"Received event {topic}", {"event_id": event["id"]})
    return {"ok": True, "event": event}



# DPN AI v5 persistent background operations
@app.get("/api/jobs")
def list_jobs(status: str | None = None, limit: int = 200) -> dict[str, Any]:
    return {"jobs": db.list_background_jobs(status, limit)}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = db.get_background_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job": job}


@app.post("/api/jobs")
async def create_job(request: BackgroundJobCreate) -> dict[str, Any]:
    result = await job_supervisor.submit(request.kind, request.payload)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict[str, Any]:
    result = await job_supervisor.cancel(job_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.post("/api/jobs/{job_id}/retry")
async def retry_job(job_id: str) -> dict[str, Any]:
    result = await job_supervisor.retry(job_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


# Provenance-aware knowledge graph
@app.get("/api/graph/stats")
def graph_stats() -> dict[str, Any]:
    return tools.graph.stats()


@app.get("/api/graph/search")
def graph_search(q: str, project_id: str | None = None, limit: int = 30) -> dict[str, Any]:
    return tools.graph.search(q, project_id, limit)


@app.post("/api/graph/nodes")
def graph_add_node(request: GraphNodeCreate) -> dict[str, Any]:
    return tools.graph.add_node(**request.model_dump())


@app.post("/api/graph/edges")
def graph_add_edge(request: GraphEdgeCreate) -> dict[str, Any]:
    result = tools.graph.add_edge(**request.model_dump())
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.post("/api/graph/facts")
def graph_add_fact(request: GraphFactCreate) -> dict[str, Any]:
    result = tools.graph.remember_fact(**request.model_dump())
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.get("/api/graph/nodes/{node_id}/neighborhood")
def graph_neighborhood(node_id: str, depth: int = 1, limit: int = 100) -> dict[str, Any]:
    result = tools.graph.neighborhood(node_id, depth, limit)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


# Model Context Protocol bridge
@app.get("/api/mcp/status")
def mcp_status() -> dict[str, Any]:
    return {**tools.mcp.status(), "servers": len(db.list_mcp_servers())}


@app.get("/api/mcp/servers")
def mcp_servers() -> dict[str, Any]:
    return tools.mcp.list_servers()


@app.post("/api/mcp/servers")
def mcp_create_server(request: MCPServerCreate) -> dict[str, Any]:
    if not agent.effective_settings().get("allow_mcp"):
        raise HTTPException(status_code=403, detail="MCP integrations are disabled in Settings")
    result = tools.mcp.create_server(**request.model_dump())
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    db.audit("mcp.server_created", f"Created MCP server {request.name}")
    return result


@app.patch("/api/mcp/servers/{server_id}")
def mcp_update_server(server_id: str, request: MCPServerPatch) -> dict[str, Any]:
    if not agent.effective_settings().get("allow_mcp"):
        raise HTTPException(status_code=403, detail="MCP integrations are disabled in Settings")
    result = tools.mcp.update_server(server_id, **request.model_dump(exclude_unset=True))
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    db.audit("mcp.server_updated", f"Updated MCP server {server_id}")
    return result


@app.delete("/api/mcp/servers/{server_id}")
def mcp_delete_server(server_id: str) -> dict[str, Any]:
    if not agent.effective_settings().get("allow_mcp"):
        raise HTTPException(status_code=403, detail="MCP integrations are disabled in Settings")
    result = tools.mcp.delete_server(server_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    db.audit("mcp.server_deleted", f"Deleted MCP server {server_id}")
    return result


@app.post("/api/mcp/servers/{server_id}/discover")
async def mcp_discover(server_id: str) -> dict[str, Any]:
    effective = agent.effective_settings()
    permissions = {**effective, "run_id": None}
    return await tools.execute("discover_mcp_tools", {"server_id": server_id}, permissions)


@app.post("/api/mcp/servers/{server_id}/tools/{tool_name}")
async def mcp_call(server_id: str, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    effective = agent.effective_settings()
    permissions = {**effective, "run_id": None}
    return await tools.execute("call_mcp_tool", {"server_id": server_id, "tool_name": tool_name, "arguments": arguments or {}}, permissions)


# Staged capability forge
@app.get("/api/capability-forge")
def list_capabilities() -> dict[str, Any]:
    return tools.forge.list()


@app.post("/api/capability-forge/stage")
def stage_capability(request: CapabilityStageRequest) -> dict[str, Any]:
    if not agent.effective_settings().get("allow_self_improvement"):
        raise HTTPException(status_code=403, detail="Capability self-improvement is disabled in Settings")
    result = tools.forge.stage(**request.model_dump())
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    db.audit("capability.staged", f"Staged capability {request.capability_id}")
    return result


@app.post("/api/capability-forge/{capability_id}/validate")
def validate_capability(capability_id: str) -> dict[str, Any]:
    if not agent.effective_settings().get("allow_self_improvement"):
        raise HTTPException(status_code=403, detail="Capability self-improvement is disabled in Settings")
    return tools.forge.validate(capability_id)


@app.post("/api/capability-forge/{capability_id}/promote")
async def promote_capability(capability_id: str) -> dict[str, Any]:
    effective = agent.effective_settings()
    permissions = {**effective, "run_id": None}
    return await tools.execute("promote_capability", {"capability_id": capability_id}, permissions)


@app.post("/api/capability-forge/{capability_id}/rollback")
async def rollback_capability(capability_id: str, backup_name: str | None = None) -> dict[str, Any]:
    effective = agent.effective_settings()
    permissions = {**effective, "run_id": None}
    return await tools.execute("rollback_capability", {"capability_id": capability_id, "backup_name": backup_name}, permissions)


# Bounded code sandbox
@app.get("/api/sandbox/status")
def sandbox_status() -> dict[str, Any]:
    return tools.sandbox.status()


@app.post("/api/sandbox/python")
async def sandbox_python(request: SandboxPythonRequest) -> dict[str, Any]:
    effective = agent.effective_settings()
    permissions = {**effective, "run_id": None}
    return await tools.execute("run_python_sandbox", request.model_dump(), permissions)


# Files, uploads, knowledge, and image workflow
@app.post("/api/images/workflow")
async def upload_comfyui_workflow(file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Workflow exceeds the 5 MB limit")
    try:
        workflow = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON workflow: {exc}") from exc
    if not isinstance(workflow, dict) or not workflow:
        raise HTTPException(status_code=400, detail="Workflow must be a non-empty ComfyUI API-format JSON object")
    target = settings.comfyui_workflow_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(workflow, indent=2), encoding="utf-8")
    return {"ok": True, "path": str(target), "nodes": len(workflow)}


@app.post("/api/files/upload")
async def upload_files(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    uploaded: list[str] = []
    failed: list[dict[str, str]] = []
    for upload in files:
        try:
            data = await upload.read()
            if len(data) > 100 * 1024 * 1024:
                raise ValueError("File exceeds the 100 MB upload limit")
            uploaded.append(tools.fs.upload_bytes(upload.filename or "upload.bin", data))
        except Exception as exc:  # noqa: BLE001
            failed.append({"filename": upload.filename or "unknown", "error": str(exc)})
    index_result = tools.knowledge.index_workspace("uploads") if uploaded else None
    return {"uploaded": uploaded, "failed": failed, "index": index_result}


@app.get("/api/files")
def list_files(path: str = ".", pattern: str = "*", recursive: bool = True) -> dict[str, Any]:
    try:
        return tools.fs.list_files(path=path, pattern=pattern, recursive=recursive, limit=3000)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/files/download/{workspace_path:path}")
def download_file(workspace_path: str) -> FileResponse:
    try:
        target = tools.fs.resolve(workspace_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    media_type, _ = mimetypes.guess_type(target.name)
    return FileResponse(target, filename=target.name, media_type=media_type or "application/octet-stream")


@app.post("/api/knowledge/index")
def index_workspace(force: bool = False) -> dict[str, Any]:
    return tools.knowledge.index_workspace(".", force=force)


@app.get("/api/knowledge/search")
def search_knowledge(q: str, limit: int = 10) -> dict[str, Any]:
    return tools.knowledge.search(q, limit=limit)


@app.get("/api/workspace/info")
def workspace_info() -> dict[str, Any]:
    return {"workspace": tools.fs.disk_summary(), "knowledge": tools.knowledge.stats()}


app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="static")