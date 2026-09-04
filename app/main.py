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


APP_VERSION = (BASE_DIR / "VERSION").read_text(encoding="utf-8").strip()
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