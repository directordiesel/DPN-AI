from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("DPN_APP_NAME", "DPN AI")
    host: str = os.getenv("DPN_HOST", "127.0.0.1")
    port: int = int(os.getenv("DPN_PORT", "8787"))
    access_token: str = os.getenv("DPN_ACCESS_TOKEN", "").strip()
    ollama_url: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    default_model: str = os.getenv("DPN_DEFAULT_MODEL", "qwen3.5:9b")
    default_provider: str = os.getenv("DPN_DEFAULT_PROVIDER", "ollama").strip().lower() or "ollama"
    compatible_api_url: str = os.getenv("DPN_COMPATIBLE_API_URL", "").rstrip("/")
    compatible_api_secret: str = os.getenv("DPN_COMPATIBLE_API_SECRET", "MODEL_PROVIDER_KEY").strip() or "MODEL_PROVIDER_KEY"
    allow_external_models_default: bool = _env_bool("DPN_ALLOW_EXTERNAL_MODELS", False)
    think_level: str = os.getenv("DPN_THINK_LEVEL", "medium")
    intelligence_mode: str = os.getenv("DPN_INTELLIGENCE_MODE", "maximum").strip().lower() or "maximum"
    keep_model_loaded: bool = _env_bool("DPN_KEEP_MODEL_LOADED", True)
    max_agent_steps: int = int(os.getenv("DPN_MAX_AGENT_STEPS", "14"))
    max_history_messages: int = int(os.getenv("DPN_MAX_HISTORY_MESSAGES", "50"))
    command_timeout_seconds: int = int(os.getenv("DPN_COMMAND_TIMEOUT", "120"))
    max_tool_output_chars: int = int(os.getenv("DPN_MAX_TOOL_OUTPUT", "32000"))
    max_tool_calls: int = int(os.getenv("DPN_MAX_TOOL_CALLS", "80"))
    max_run_seconds: int = int(os.getenv("DPN_MAX_RUN_SECONDS", "1800"))
    max_mission_steps: int = int(os.getenv("DPN_MAX_MISSION_STEPS", "12"))
    planner_model: str = os.getenv("DPN_PLANNER_MODEL", "")
    worker_model: str = os.getenv("DPN_WORKER_MODEL", "")
    reviewer_model: str = os.getenv("DPN_REVIEWER_MODEL", "")
    embedding_model: str = os.getenv("DPN_EMBEDDING_MODEL", "nomic-embed-text")
    allow_commands_default: bool = _env_bool("DPN_ALLOW_COMMANDS", False)
    allow_web_default: bool = _env_bool("DPN_ALLOW_WEB", True)
    allow_images_default: bool = _env_bool("DPN_ALLOW_IMAGES", False)
    allow_automations_default: bool = _env_bool("DPN_ALLOW_AUTOMATIONS", False)
    allow_browser_default: bool = _env_bool("DPN_ALLOW_BROWSER", False)
    allow_desktop_default: bool = _env_bool("DPN_ALLOW_DESKTOP", False)
    allow_voice_default: bool = _env_bool("DPN_ALLOW_VOICE", False)
    allow_connectors_default: bool = _env_bool("DPN_ALLOW_CONNECTORS", False)
    allow_mcp_default: bool = _env_bool("DPN_ALLOW_MCP", False)
    allow_self_improvement_default: bool = _env_bool("DPN_ALLOW_SELF_IMPROVEMENT", False)
    allow_host_sandbox_default: bool = _env_bool("DPN_ALLOW_HOST_SANDBOX", False)
    allow_external_mcp_default: bool = _env_bool("DPN_ALLOW_EXTERNAL_MCP", False)
    max_parallel_jobs: int = int(os.getenv("DPN_MAX_PARALLEL_JOBS", "2"))
    review_quorum: int = int(os.getenv("DPN_REVIEW_QUORUM", "2"))
    allow_private_network: bool = _env_bool("DPN_ALLOW_PRIVATE_NETWORK", False)
    comfyui_url: str = os.getenv("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
    data_dir: Path = Path(os.getenv("DPN_DATA_DIR", str(BASE_DIR / "data"))).resolve()
    workspace_dir: Path = Path(os.getenv("DPN_WORKSPACE_DIR", str(BASE_DIR / "workspace"))).resolve()
    static_dir: Path = BASE_DIR / "app" / "static"
    skills_dir: Path = Path(os.getenv("DPN_SKILLS_DIR", str(BASE_DIR / "skills"))).resolve()
    vault_key_path: Path = Path(os.getenv("DPN_VAULT_KEY", str(data_dir / "vault.key"))).resolve()
    voice_dir: Path = Path(os.getenv("DPN_VOICE_DIR", str(data_dir / "voices"))).resolve()
    plugins_dir: Path = Path(os.getenv("DPN_PLUGINS_DIR", str(BASE_DIR / "plugins"))).resolve()

    @property
    def comfyui_workflow_path(self) -> Path:
        return Path(os.getenv("DPN_COMFYUI_WORKFLOW", str(self.data_dir / "comfyui_workflow_api.json"))).resolve()

    @property
    def database_path(self) -> Path:
        return self.data_dir / "dpn_ai.sqlite3"

    @property
    def snapshots_dir(self) -> Path:
        return self.data_dir / "snapshots"

    @property
    def exports_dir(self) -> Path:
        return self.workspace_dir / "generated" / "exports"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.workspace_dir.mkdir(parents=True, exist_ok=True)
settings.snapshots_dir.mkdir(parents=True, exist_ok=True)
settings.exports_dir.mkdir(parents=True, exist_ok=True)
settings.skills_dir.mkdir(parents=True, exist_ok=True)
settings.voice_dir.mkdir(parents=True, exist_ok=True)
settings.plugins_dir.mkdir(parents=True, exist_ok=True)