from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AgentProfile = Literal["auto", "director", "software", "fivem", "research", "business", "documents", "security", "media", "automation", "computer", "data", "science", "creative"]


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=100_000)
    model: str | None = None
    think: bool | str | None = None
    attachments: list[str] = Field(default_factory=list)
    profile: AgentProfile = "auto"
    project_id: str | None = None
    execution_mode: Literal["auto", "direct", "mission"] = "auto"
    skill_ids: list[str] = Field(default_factory=list, max_length=8)
    verify: bool = False
    budget: dict[str, Any] = Field(default_factory=dict)
    edit_message_id: int | None = Field(default=None, ge=1)


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", max_length=120)


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class SettingsPatch(BaseModel):
    model: str | None = None
    default_provider: Literal["ollama", "compatible"] | None = None
    compatible_api_url: str | None = Field(default=None, max_length=1000)
    compatible_api_secret: str | None = Field(default=None, max_length=120)
    allow_external_models: bool | None = None
    think_level: bool | str | None = None
    intelligence_mode: Literal["maximum", "balanced", "manual"] | None = None
    keep_model_loaded: bool | None = None
    allow_commands: bool | None = None
    allow_web: bool | None = None
    allow_images: bool | None = None
    allow_automations: bool | None = None
    command_timeout_seconds: int | None = Field(default=None, ge=5, le=900)
    approval_mode: Literal["safe", "standard", "autonomous"] | None = None
    allow_browser: bool | None = None
    allow_desktop: bool | None = None
    allow_voice: bool | None = None
    allow_connectors: bool | None = None
    allow_mcp: bool | None = None
    allow_self_improvement: bool | None = None
    allow_host_sandbox: bool | None = None
    planner_model: str | None = None
    worker_model: str | None = None
    reviewer_model: str | None = None
    embedding_model: str | None = None
    model_routes: dict[str, str] | None = None
    max_tool_calls: int | None = Field(default=None, ge=1, le=1000)
    max_run_seconds: int | None = Field(default=None, ge=30, le=86400)


class VoiceSynthesisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    voice_id: Literal["sentinel", "aurora", "system"] = "sentinel"
    speed: float | None = Field(default=None, ge=0.55, le=1.8)
    volume: float = Field(default=1.0, ge=0.1, le=2.0)
    filename: str = Field(default="dpn-ai-speech.wav", max_length=200)
    use_cuda: bool = False
    tone: Literal["clear", "natural", "warm", "gentle"] | None = None


class VoiceTranscriptionOptions(BaseModel):
    model_size: str = Field(default="base", max_length=80)
    language: str | None = Field(default=None, max_length=20)
    initial_prompt: str | None = Field(default=None, max_length=2000)


class MemoryCreate(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=20_000)


class PullModelRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=10_000)
    root_path: str = Field(default=".", max_length=500)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=10_000)
    root_path: str | None = Field(default=None, max_length=500)
    status: Literal["active", "paused", "completed", "archived"] | None = None


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    details: str = Field(default="", max_length=30_000)
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    dependencies: list[str] = Field(default_factory=list)


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    details: str | None = Field(default=None, max_length=30_000)
    status: Literal["backlog", "ready", "running", "blocked", "done", "failed"] | None = None
    priority: Literal["low", "normal", "high", "critical"] | None = None
    result: dict[str, Any] | None = None


class SnapshotCreate(BaseModel):
    name: str = Field(default="manual-snapshot", max_length=120)
    path: str = Field(default=".", max_length=500)


class AutomationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=50_000)
    schedule_type: Literal["interval", "daily"]
    schedule_value: str = Field(min_length=1, max_length=80)
    profile: AgentProfile = "auto"
    project_id: str | None = None
    enabled: bool = True


class AutomationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    prompt: str | None = Field(default=None, min_length=1, max_length=50_000)
    schedule_type: Literal["interval", "daily"] | None = None
    schedule_value: str | None = Field(default=None, min_length=1, max_length=80)
    profile: AgentProfile | None = None
    project_id: str | None = None
    enabled: bool | None = None


class ToolTrace(BaseModel):
    name: str
    arguments: dict[str, Any]
    result: Any
    ok: bool
    elapsed_ms: int


class ChatResponse(BaseModel):
    conversation_id: str
    run_id: str | None = None
    message: str
    model: str
    profile: str = "auto"
    thinking: str | None = None
    traces: list[ToolTrace] = Field(default_factory=list)
    generated_files: list[str] = Field(default_factory=list)
    user_message_id: int | None = None
    intelligence_mode: str = "maximum"


class ApprovalDecision(BaseModel):
    decision: Literal["approved", "denied"]


class ConnectorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=8, max_length=2000)
    headers: dict[str, str] = Field(default_factory=dict)
    allowed_methods: list[str] = Field(default_factory=lambda: ["GET"])
    enabled: bool = True


class SecretCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=100_000)


class SkillCreate(BaseModel):
    skill_id: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    instructions: str = Field(min_length=1, max_length=100_000)
    examples: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    overwrite: bool = False


class SemanticCreate(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)
    namespace: str = Field(default="global", max_length=100)
    source: str = Field(default="manual", max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=5000)
    steps: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    enabled: bool = True


class WorkflowRunRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)


class MissionCreate(BaseModel):
    objective: str = Field(min_length=1, max_length=100_000)
    conversation_id: str | None = None
    project_id: str | None = None
    attachments: list[str] = Field(default_factory=list)
    profile: AgentProfile = "auto"
    model: str | None = None
    think: bool | str | None = None
    budget: dict[str, Any] = Field(default_factory=dict)
    edit_message_id: int | None = Field(default=None, ge=1)


class BackgroundJobCreate(BaseModel):
    kind: Literal["direct", "mission", "workflow"]
    payload: dict[str, Any] = Field(default_factory=dict)


class MCPServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    transport: Literal["stdio", "http"]
    command: str | None = Field(default=None, max_length=1000)
    args: list[str] = Field(default_factory=list, max_length=100)
    url: str | None = Field(default=None, max_length=2000)
    env: dict[str, str] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list, max_length=500)
    enabled: bool = True


class MCPServerPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    allowed_tools: list[str] | None = Field(default=None, max_length=500)
    enabled: bool | None = None


class GraphNodeCreate(BaseModel):
    label: str = Field(min_length=1, max_length=500)
    node_type: str = Field(default="entity", max_length=80)
    data: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: str = Field(default="manual", max_length=1000)
    project_id: str | None = None
    node_id: str | None = None


class GraphEdgeCreate(BaseModel):
    source_id: str
    relation: str = Field(min_length=1, max_length=120)
    target_id: str
    data: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: str = Field(default="manual", max_length=1000)


class GraphFactCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    relation: str = Field(min_length=1, max_length=120)
    object_value: str = Field(min_length=1, max_length=500)
    source: str = Field(default="manual", max_length=1000)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    project_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityStageRequest(BaseModel):
    capability_id: str = Field(min_length=1, max_length=80)
    code: str = Field(min_length=1, max_length=1_000_000)
    description: str = Field(default="", max_length=5000)
    overwrite: bool = False


class SandboxPythonRequest(BaseModel):
    code: str = Field(min_length=1, max_length=500_000)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    memory_mb: int = Field(default=512, ge=64, le=4096)
    network: bool = False
    use_host_fallback: bool = False