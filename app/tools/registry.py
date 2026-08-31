from __future__ import annotations

import inspect
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.config import Settings
from app.capability_forge import CapabilityForge
from app.cognitive_kernel import CognitiveKernel
from app.knowledge_graph import KnowledgeGraph
from app.mcp_bridge import MCPBridge
from app.sandbox import SandboxManager
from app.archive_tools import ArchiveTools
from app.browser_adapter import BrowserAdapter
from app.connectors import ConnectorHub
from app.desktop_adapter import DesktopAdapter
from app.media import MediaTools
from app.ollama_client import OllamaClient
from app.semantic import SemanticMemory
from app.skills import SkillManager
from app.vault import SecretVault
from app.voice_adapter import VoiceAdapter
from app.db import Database
from app.plugins import load_plugins
from app.services import DiagnosticService, SnapshotService
from app.tools.documents import DocumentFactory
from app.tools.filesystem import WorkspaceFS
from app.tools.images import ComfyUIImageGenerator
from app.tools.knowledge import KnowledgeBase
from app.tools.shell import SafeCommandRunner
from app.tools.web_tools import fetch_web_page, search_web


ToolFunction = Callable[..., Any] | Callable[..., Awaitable[Any]]


@dataclass
class RegisteredTool:
    schema: dict[str, Any]
    function: ToolFunction
    gate: str | None = None
    risk: str = "read"


class ToolRegistry:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.fs = WorkspaceFS(settings.workspace_dir)
        self.documents = DocumentFactory(settings.workspace_dir)
        self.knowledge = KnowledgeBase(db, self.fs)
        self.images = ComfyUIImageGenerator(settings.comfyui_url, settings.comfyui_workflow_path, settings.workspace_dir)
        self.shell = SafeCommandRunner(settings.workspace_dir, settings.command_timeout_seconds, settings.max_tool_output_chars)
        self.snapshots = SnapshotService(settings, db, self.fs)
        self.diagnostics = DiagnosticService(settings, db, self.fs)
        self.ollama = OllamaClient(settings.ollama_url)
        self.skills = SkillManager(settings.skills_dir)
        self.vault = SecretVault(settings.vault_key_path, settings.data_dir / "vault.json")
        self.semantic = SemanticMemory(db, self.ollama, settings.embedding_model)
        self.connectors = ConnectorHub(db, self.vault, settings.allow_private_network)
        self.browser = BrowserAdapter(settings.workspace_dir, settings.allow_private_network)
        self.desktop = DesktopAdapter(settings.workspace_dir)
        self.voice = VoiceAdapter(settings.workspace_dir, settings.data_dir)
        self.media = MediaTools(settings.workspace_dir)
        self.archives = ArchiveTools(settings.workspace_dir)
        self.cognitive = CognitiveKernel(db, settings.workspace_dir)
        self.graph = KnowledgeGraph(db)
        self.sandbox = SandboxManager(settings.workspace_dir, settings.allow_host_sandbox_default)
        self.forge = CapabilityForge(settings.plugins_dir, settings.data_dir)
        self.mcp = MCPBridge(db, self.vault, settings.allow_external_mcp_default)
        self.tools: dict[str, RegisteredTool] = {}
        self._register_defaults()
        self.plugin_errors = load_plugins(settings.plugins_dir, self)

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        function: ToolFunction,
        gate: str | None = None,
        risk: str = "read",
    ) -> None:
        self.tools[name] = RegisteredTool(
            schema={"type": "function", "function": {"name": name, "description": description, "parameters": parameters}},
            function=function,
            gate=gate,
            risk=risk,
        )

    def schemas(self, names: set[str] | list[str] | None = None) -> list[dict[str, Any]]:
        if names is None:
            return [tool.schema for tool in self.tools.values()]
        selected = set(names)
        return [tool.schema for name, tool in self.tools.items() if name in selected]

    def select_names(self, query: str, profile: str = "auto", skill_ids: list[str] | None = None, limit: int = 34) -> set[str]:
        """Select a focused initial tool context while preserving on-demand discovery."""
        query_lower = (query or "").lower()
        core = {
            "discover_tools", "list_files", "directory_tree", "read_file", "search_text", "write_file",
            "replace_text", "make_directory", "file_hash", "search_knowledge", "remember",
            "analyze_goal", "list_projects", "list_project_tasks", "create_project_task",
        }
        groups: dict[str, set[str]] = {
            "software": {"run_command", "copy_path", "delete_path", "create_workspace_snapshot", "sandbox_status", "run_python_sandbox", "stage_capability", "validate_capability"},
            "fivem": {"run_command", "copy_path", "delete_path", "create_workspace_snapshot", "sandbox_status", "run_python_sandbox"},
            "research": {"search_web", "fetch_web_page", "semantic_search", "semantic_remember", "graph_search", "graph_neighborhood", "remember_graph_fact"},
            "business": {"create_word_document", "create_pdf", "create_spreadsheet", "create_presentation", "semantic_search", "graph_search"},
            "documents": {"create_word_document", "create_pdf", "create_spreadsheet", "create_presentation", "index_workspace"},
            "security": {"system_diagnostics", "file_hash", "create_workspace_snapshot", "list_audit_events", "inspect_archive", "sandbox_status", "mcp_status"},
            "media": {"generate_image", "media_status", "probe_media", "prepare_media_for_ai", "transcode_media", "extract_media_audio", "speak_text", "transcribe_audio"},
            "automation": {"list_connectors", "connector_request", "browser_status", "browser_automation", "mcp_status", "list_mcp_servers", "create_mcp_server", "update_mcp_server", "discover_mcp_tools", "call_mcp_tool"},
            "computer": {"desktop_status", "observe_screen", "desktop_automation", "browser_status", "browser_automation", "voice_status", "speak_text"},
            "data": {"run_command", "run_python_sandbox", "create_spreadsheet", "search_knowledge", "index_workspace", "graph_search"},
            "science": {"run_python_sandbox", "search_web", "fetch_web_page", "semantic_search", "graph_search"},
            "creative": {"create_word_document", "create_pdf", "create_presentation", "generate_image", "speak_text", "transcode_media"},
            "director": {"system_diagnostics", "create_workspace_snapshot", "semantic_search", "graph_search", "list_skills", "list_workflows"},
        }
        selected = set(core) | groups.get(profile, set())
        keyword_groups = [
            (("web", "latest", "research", "source"), groups["research"]),
            (("screen", "desktop", "click", "browser", "computer"), groups["computer"]),
            (("voice", "speak", "audio", "video", "image"), groups["media"]),
            (("document", "pdf", "excel", "spreadsheet", "presentation"), groups["documents"]),
            (("code", "debug", "test", "script", "app", "api"), groups["software"]),
            (("mcp", "connector", "integration", "workflow"), groups["automation"]),
            (("data", "csv", "analytics", "statistics", "chart"), groups["data"]),
        ]
        for keywords, names in keyword_groups:
            if any(keyword in query_lower for keyword in keywords):
                selected |= names
        for skill_id in skill_ids or []:
            skill = self.skills.get(skill_id)
            for name in (skill.get("skill") or {}).get("allowed_tools", []):
                if name in self.tools:
                    selected.add(name)
        ordered = [name for name in self.tools if name in selected]
        return set(ordered[:max(10, min(limit, 80))])

    def discover(self, query: str = "", risk: str | None = None, gate: str | None = None, limit: int = 40) -> dict[str, Any]:
        words = [item for item in query.lower().split() if len(item) > 2]
        matches = []
        for item in self.catalog():
            haystack = f"{item['name']} {item['description']}".lower()
            if words and not all(word in haystack for word in words):
                continue
            if risk and item["risk"] != risk:
                continue
            if gate and item["gate"] != gate:
                continue
            matches.append(item)
        return {"ok": True, "count": len(matches[:limit]), "tools": matches[:max(1, min(limit, 200))]}

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "description": tool.schema["function"]["description"],
                "gate": tool.gate,
                "risk": tool.risk,
            }
            for name, tool in self.tools.items()
        ]

    def _register_defaults(self) -> None:
        object_schema = lambda properties, required=None: {  # noqa: E731
            "type": "object", "properties": properties, "required": required or [], "additionalProperties": False,
        }

        self.register("discover_tools", "Discover additional DPN AI tools by capability, risk, or permission gate.", object_schema({
            "query": {"type": "string", "default": ""}, "risk": {"type": ["string", "null"], "default": None},
            "gate": {"type": ["string", "null"], "default": None}, "limit": {"type": "integer", "default": 40},
        }), self.discover)
        self.register("analyze_goal", "Convert an open-ended objective into an explicit success contract with capabilities, risks, unknowns, and evidence criteria.", object_schema({
            "objective": {"type": "string"}, "constraints": {"type": "array", "items": {"type": "string"}, "default": []},
        }, ["objective"]), self._analyze_goal)
        self.register("list_files", "List files and directories inside the restricted DPN AI workspace.", object_schema({
            "path": {"type": "string", "default": "."}, "pattern": {"type": "string", "default": "*"},
            "recursive": {"type": "boolean", "default": True}, "limit": {"type": "integer", "default": 500},
        }), self.fs.list_files)
        self.register("directory_tree", "Build a compact workspace directory tree before planning changes.", object_schema({
            "path": {"type": "string", "default": "."}, "max_depth": {"type": "integer", "default": 4},
            "max_entries": {"type": "integer", "default": 700},
        }), self.fs.directory_tree)
        self.register("read_file", "Read a UTF-8 text/code file from the workspace with line numbers.", object_schema({
            "path": {"type": "string"}, "start_line": {"type": "integer", "default": 1},
            "end_line": {"type": ["integer", "null"], "default": None},
        }, ["path"]), self.fs.read_file)
        self.register("search_text", "Search text and code across workspace files with line-level matches.", object_schema({
            "query": {"type": "string"}, "path": {"type": "string", "default": "."},
            "pattern": {"type": "string", "default": "*"}, "case_sensitive": {"type": "boolean", "default": False},
            "limit": {"type": "integer", "default": 100},
        }, ["query"]), self.fs.search_text)
        self.register("write_file", "Create or overwrite a text/code file in the DPN AI workspace.", object_schema({
            "path": {"type": "string"}, "content": {"type": "string"}, "overwrite": {"type": "boolean", "default": True},
        }, ["path", "content"]), self.fs.write_file, risk="write")
        self.register("replace_text", "Safely edit a text file by replacing exact text. Prefer this over rewriting an entire existing file.", object_schema({
            "path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"},
            "replace_all": {"type": "boolean", "default": False},
        }, ["path", "old_text", "new_text"]), self.fs.replace_text, risk="write")
        self.register("copy_path", "Copy one file or directory within the workspace.", object_schema({
            "source": {"type": "string"}, "destination": {"type": "string"}, "overwrite": {"type": "boolean", "default": False},
        }, ["source", "destination"]), self.fs.copy_path, risk="write")
        self.register("file_hash", "Calculate a cryptographic file hash for verification.", object_schema({
            "path": {"type": "string"}, "algorithm": {"type": "string", "default": "sha256"},
        }, ["path"]), self.fs.file_hash)
        self.register("make_directory", "Create a directory inside the workspace.", object_schema({"path": {"type": "string"}}, ["path"]), self.fs.make_directory, risk="write")
        self.register("delete_path", "Delete one file or an empty directory. Recursive deletion remains disabled.", object_schema({"path": {"type": "string"}}, ["path"]), self.fs.delete_path, risk="destructive")
        self.register("run_command", "Run a controlled development command in the workspace. Command execution must be enabled.", object_schema({
            "command": {"type": "string"}, "cwd": {"type": "string", "default": "."},
            "timeout_seconds": {"type": ["integer", "null"], "default": None},
        }, ["command"]), self.shell.run, gate="commands", risk="execute")

        self.register("index_workspace", "Index supported workspace files for local document and code search.", object_schema({
            "path": {"type": "string", "default": "."}, "force": {"type": "boolean", "default": False},
            "max_files": {"type": "integer", "default": 1000},
        }), self.knowledge.index_workspace, risk="write")
        self.register("search_knowledge", "Search indexed local documents, uploads, and code.", object_schema({
            "query": {"type": "string"}, "limit": {"type": "integer", "default": 8},
        }, ["query"]), self.knowledge.search)
        self.register("remember", "Store a durable preference, project fact, naming convention, or decision in local memory.", object_schema({
            "key": {"type": "string"}, "value": {"type": "string"},
        }, ["key", "value"]), self._remember, risk="write")
        self.register("list_memories", "List durable local memories.", object_schema({}), self._list_memories)

        self.register("list_projects", "List DPN AI projects and task counts.", object_schema({"include_archived": {"type": "boolean", "default": False}}), self._list_projects)
        self.register("create_project", "Create a persistent project linked to a workspace root.", object_schema({
            "name": {"type": "string"}, "description": {"type": "string", "default": ""}, "root_path": {"type": "string", "default": "."},
        }, ["name"]), self._create_project, risk="write")
        self.register("create_project_task", "Create a task in a persistent project task board.", object_schema({
            "project_id": {"type": "string"}, "title": {"type": "string"}, "details": {"type": "string", "default": ""},
            "priority": {"type": "string", "enum": ["low", "normal", "high", "critical"], "default": "normal"},
            "dependencies": {"type": "array", "items": {"type": "string"}, "default": []},
        }, ["project_id", "title"]), self._create_task, risk="write")
        self.register("list_project_tasks", "List tasks for a project.", object_schema({
            "project_id": {"type": "string"}, "status": {"type": ["string", "null"], "default": None},
        }, ["project_id"]), self._list_tasks)
        self.register("update_project_task", "Update a project task's status, priority, details, or result.", object_schema({
            "task_id": {"type": "string"}, "status": {"type": ["string", "null"], "default": None},
            "priority": {"type": ["string", "null"], "default": None}, "details": {"type": ["string", "null"], "default": None},
            "result": {"type": ["object", "null"], "default": None},
        }, ["task_id"]), self._update_task, risk="write")
        self.register("create_workspace_snapshot", "Create a verified ZIP snapshot before major code or content changes.", object_schema({
            "name": {"type": "string", "default": "agent-snapshot"}, "path": {"type": "string", "default": "."},
        }), self.snapshots.create, risk="write")
        self.register("list_workspace_snapshots", "List local workspace snapshots.", object_schema({}), self.snapshots.list)
        self.register("system_diagnostics", "Inspect local hardware, disk, workspace, and database health.", object_schema({}), self.diagnostics.report)

        self.register("create_word_document", "Create a professionally formatted DPN-themed Word document in workspace/generated.", object_schema({
            "filename": {"type": "string"}, "title": {"type": "string"}, "sections": {"type": "array", "items": {"type": "object"}},
            "author": {"type": "string", "default": "DPN AI"},
        }, ["filename", "title", "sections"]), self.documents.create_docx, risk="write")
        self.register("create_pdf", "Create a DPN-themed PDF report in workspace/generated.", object_schema({
            "filename": {"type": "string"}, "title": {"type": "string"}, "sections": {"type": "array", "items": {"type": "object"}},
        }, ["filename", "title", "sections"]), self.documents.create_pdf, risk="write")
        self.register("create_spreadsheet", "Create a formatted Excel workbook in workspace/generated.", object_schema({
            "filename": {"type": "string"}, "title": {"type": "string"}, "sheets": {"type": "array", "items": {"type": "object"}},
        }, ["filename", "title", "sheets"]), self.documents.create_xlsx, risk="write")
        self.register("create_presentation", "Create a red-and-black DPN-themed PowerPoint presentation in workspace/generated.", object_schema({
            "filename": {"type": "string"}, "title": {"type": "string"}, "slides": {"type": "array", "items": {"type": "object"}},
        }, ["filename", "title", "slides"]), self.documents.create_pptx, risk="write")
        self.register("generate_image", "Generate an image locally through ComfyUI using the configured API workflow.", object_schema({
            "prompt": {"type": "string"}, "negative_prompt": {"type": "string", "default": "low quality, blurry, distorted, watermark, text artifacts"},
            "filename_prefix": {"type": "string", "default": "DPN_AI"}, "seed": {"type": ["integer", "null"], "default": None},
            "timeout_seconds": {"type": "integer", "default": 300},
        }, ["prompt"]), self.images.generate, gate="images", risk="external")
        self.register("search_web", "Search the public web for current information.", object_schema({
            "query": {"type": "string"}, "max_results": {"type": "integer", "default": 6},
        }, ["query"]), search_web, gate="web", risk="external")
        self.register("fetch_web_page", "Fetch readable text from a public web page after search. Private network access is blocked.", object_schema({
            "url": {"type": "string"}, "max_chars": {"type": "integer", "default": 20000},
        }, ["url"]), fetch_web_page, gate="web", risk="external")


        # Universal v3 capability layer
        self.register("list_skills", "List reusable DPN AI skill packs.", object_schema({}), self.skills.list)
        self.register("read_skill", "Read one reusable DPN AI skill pack.", object_schema({
            "skill_id": {"type": "string"},
        }, ["skill_id"]), self.skills.get)
        self.register("create_skill", "Create or update a reusable local skill pack.", object_schema({
            "skill_id": {"type": "string"}, "name": {"type": "string"}, "description": {"type": "string"},
            "instructions": {"type": "string"}, "examples": {"type": "array", "items": {"type": "string"}, "default": []},
            "allowed_tools": {"type": "array", "items": {"type": "string"}, "default": []},
            "overwrite": {"type": "boolean", "default": False},
        }, ["skill_id", "name", "description", "instructions"]), self.skills.create, risk="write")
        self.register("semantic_remember", "Embed and save knowledge in semantic memory for meaning-based recall.", object_schema({
            "content": {"type": "string"}, "namespace": {"type": "string", "default": "global"},
            "source": {"type": "string", "default": "agent"}, "metadata": {"type": "object", "default": {}},
        }, ["content"]), self.semantic.add, risk="write")
        self.register("semantic_search", "Search semantic memory by meaning using local embeddings.", object_schema({
            "query": {"type": "string"}, "namespace": {"type": "string", "default": "global"},
            "limit": {"type": "integer", "default": 8},
        }, ["query"]), self.semantic.search)
        self.register("list_connectors", "List configured connector names and redacted settings.", object_schema({}), self.connectors.list)
        self.register("connector_request", "Call an allow-listed connector using encrypted secret templates.", object_schema({
            "connector_id": {"type": "string"}, "method": {"type": "string", "default": "GET"},
            "path": {"type": "string", "default": ""}, "params": {"type": ["object", "null"], "default": None},
            "json_body": {}, "timeout_seconds": {"type": "integer", "default": 30},
        }, ["connector_id"]), self.connectors.request, gate="connectors", risk="external")
        self.register("browser_status", "Check whether optional local Playwright browser automation is installed.", object_schema({}), self.browser.status)
        self.register("browser_automation", "Operate a browser using a bounded list of navigation, click, fill, press, and wait actions.", object_schema({
            "url": {"type": "string"}, "actions": {"type": "array", "items": {"type": "object"}, "default": []},
            "screenshot_name": {"type": "string", "default": "browser-result.png"}, "headless": {"type": "boolean", "default": True},
        }, ["url"]), self.browser.run, gate="browser", risk="external")
        self.register("desktop_status", "Check whether optional local desktop automation is installed.", object_schema({}), self.desktop.status)
        self.register("desktop_automation", "Control the local keyboard and mouse using bounded actions and capture a final screenshot.", object_schema({
            "actions": {"type": "array", "items": {"type": "object"}, "maxItems": 30},
            "screenshot_name": {"type": "string", "default": "desktop-result.png"},
        }, ["actions"]), self.desktop.run, gate="desktop", risk="desktop")
        # DPN AI v5 conversational voice and universal media layer
        self.register("voice_status", "Check local speech recognition, neural voice packs, and voice caches.", object_schema({}), self.voice.diagnostics)
        self.register("list_voice_profiles", "List the original DPN Sentinel male voice, DPN Aurora female voice, and system fallback.", object_schema({}), self.voice.profiles)
        self.register("install_voice_profile", "Download one approved local Piper voice profile into the DPN AI data directory.", object_schema({
            "voice_id": {"type": "string", "enum": ["sentinel", "aurora", "system"]},
        }, ["voice_id"]), self.voice.install_profile, gate="voice", risk="external")
        self.register("transcribe_audio", "Transcribe a workspace audio file using cached local faster-whisper with voice activity detection.", object_schema({
            "path": {"type": "string"}, "model_size": {"type": "string", "default": "base"},
            "language": {"type": ["string", "null"], "default": None},
            "initial_prompt": {"type": ["string", "null"], "default": None},
        }, ["path"]), self.voice.transcribe, gate="voice", risk="execute")
        self.register("speak_text", "Generate speech with DPN Sentinel, DPN Aurora, or the operating-system fallback voice.", object_schema({
            "text": {"type": "string"}, "filename": {"type": "string", "default": "dpn-ai-speech.wav"},
            "voice_id": {"type": "string", "enum": ["sentinel", "aurora", "system"], "default": "sentinel"},
            "speed": {"type": ["number", "null"], "default": None}, "volume": {"type": "number", "default": 1.0},
            "use_cuda": {"type": "boolean", "default": False},
        }, ["text"]), self.voice.speak, gate="voice", risk="write")
        self.register("clear_voice_caches", "Release cached neural speech and transcription models from memory.", object_schema({}), self.voice.clear_caches, gate="voice", risk="execute")
        self.register("media_status", "Check local ffmpeg and ffprobe availability and supported media context formats.", object_schema({}), self.media.status)
        self.register("probe_media", "Inspect technical metadata for a workspace audio or video file.", object_schema({
            "path": {"type": "string"},
        }, ["path"]), self.media.probe, risk="execute")
        self.register("extract_media_audio", "Extract 16 kHz mono speech audio from a workspace audio or video file.", object_schema({
            "input_path": {"type": "string"}, "output_name": {"type": ["string", "null"], "default": None},
        }, ["input_path"]), self.media.extract_audio, gate="commands", risk="execute")
        self.register("prepare_media_for_ai", "Extract bounded keyframes, speech audio, duration, and metadata for multimodal analysis.", object_schema({
            "path": {"type": "string"}, "max_frames": {"type": "integer", "default": 6},
        }, ["path"]), self.media.prepare_ai_context, gate="commands", risk="execute")
        self.register("transcode_media", "Transcode a workspace media file with allow-listed codecs and arguments.", object_schema({
            "input_path": {"type": "string"}, "output_name": {"type": "string"},
            "video_codec": {"type": "string", "default": "libx264"}, "audio_codec": {"type": "string", "default": "aac"},
            "extra_args": {"type": "array", "items": {"type": "string"}, "default": []},
        }, ["input_path", "output_name"]), self.media.transcode, gate="commands", risk="execute")
        self.register("inspect_archive", "Safely list ZIP or TAR archive contents and detect traversal, links, and expansion risk.", object_schema({
            "path": {"type": "string"}, "limit": {"type": "integer", "default": 2000},
        }, ["path"]), self.archives.inspect)
        self.register("extract_archive", "Safely extract a bounded ZIP or TAR archive into workspace/generated/extracted.", object_schema({
            "path": {"type": "string"}, "destination": {"type": ["string", "null"], "default": None},
            "max_files": {"type": "integer", "default": 5000}, "max_bytes": {"type": "integer", "default": 2000000000},
            "overwrite": {"type": "boolean", "default": False},
        }, ["path"]), self.archives.extract, risk="write")


        # DPN AI v5 cognitive, graph, sandbox, MCP, and capability-forge layer
        self.register("graph_stats", "Show local provenance-aware knowledge graph statistics.", object_schema({}), self.graph.stats)
        self.register("graph_add_node", "Add or update a typed knowledge-graph node with source and confidence.", object_schema({
            "label": {"type": "string"}, "node_type": {"type": "string", "default": "entity"},
            "data": {"type": "object", "default": {}}, "confidence": {"type": "number", "default": 1.0},
            "source": {"type": "string", "default": "agent"}, "project_id": {"type": ["string", "null"], "default": None},
            "node_id": {"type": ["string", "null"], "default": None},
        }, ["label"]), self.graph.add_node, risk="write")
        self.register("remember_graph_fact", "Remember a subject-relation-object fact with provenance and confidence.", object_schema({
            "subject": {"type": "string"}, "relation": {"type": "string"}, "object_value": {"type": "string"},
            "source": {"type": "string", "default": "agent"}, "confidence": {"type": "number", "default": 0.8},
            "project_id": {"type": ["string", "null"], "default": None}, "metadata": {"type": "object", "default": {}},
        }, ["subject", "relation", "object_value"]), self.graph.remember_fact, risk="write")
        self.register("graph_ingest_triples", "Ingest multiple provenance-backed knowledge graph triples.", object_schema({
            "triples": {"type": "array", "items": {"type": "object"}}, "source": {"type": "string", "default": "agent"},
            "project_id": {"type": ["string", "null"], "default": None},
        }, ["triples"]), self.graph.ingest_triples, risk="write")
        self.register("graph_search", "Search knowledge graph entities and facts by label.", object_schema({
            "query": {"type": "string"}, "project_id": {"type": ["string", "null"], "default": None},
            "limit": {"type": "integer", "default": 30},
        }, ["query"]), self.graph.search)
        self.register("graph_neighborhood", "Read a bounded multi-hop neighborhood around a graph node.", object_schema({
            "node_id": {"type": "string"}, "depth": {"type": "integer", "default": 1}, "limit": {"type": "integer", "default": 100},
        }, ["node_id"]), self.graph.neighborhood)
        self.register("sandbox_status", "Check Docker-backed isolated Python execution readiness.", object_schema({}), self.sandbox.status)
        self.register("run_python_sandbox", "Run Python in a bounded no-network Docker sandbox, with an explicitly enabled non-secure host fallback.", object_schema({
            "code": {"type": "string"}, "timeout_seconds": {"type": "integer", "default": 30},
            "memory_mb": {"type": "integer", "default": 512}, "network": {"type": "boolean", "default": False},
            "use_host_fallback": {"type": "boolean", "default": False},
        }, ["code"]), self.sandbox.run_python, gate="commands", risk="execute")
        self.register("list_capabilities", "List active and staged local capability plugins.", object_schema({}), self.forge.list)
        self.register("stage_capability", "Stage a new trusted DPN AI plugin without activating it.", object_schema({
            "capability_id": {"type": "string"}, "code": {"type": "string"}, "description": {"type": "string", "default": ""},
            "overwrite": {"type": "boolean", "default": False},
        }, ["capability_id", "code"]), self.forge.stage, gate="self_improvement", risk="write")
        self.register("validate_capability", "Parse, compile, and statically inspect a staged capability before promotion.", object_schema({
            "capability_id": {"type": "string"},
        }, ["capability_id"]), self.forge.validate, gate="self_improvement", risk="execute")
        self.register("promote_capability", "Promote a validated staged capability into the trusted plugin directory. Restart required.", object_schema({
            "capability_id": {"type": "string"},
        }, ["capability_id"]), self.forge.promote, gate="self_improvement", risk="destructive")
        self.register("rollback_capability", "Restore the most recent preserved plugin backup. Restart required.", object_schema({
            "capability_id": {"type": "string"}, "backup_name": {"type": ["string", "null"], "default": None},
        }, ["capability_id"]), self.forge.rollback, gate="self_improvement", risk="destructive")
        self.register("mcp_status", "Check optional Model Context Protocol client readiness.", object_schema({}), self.mcp.status)
        self.register("list_mcp_servers", "List configured MCP servers with secrets redacted.", object_schema({}), self.mcp.list_servers)
        self.register("create_mcp_server", "Configure a deny-by-default MCP stdio or HTTP server with an explicit tool allowlist.", object_schema({
            "name": {"type": "string"}, "transport": {"type": "string", "enum": ["stdio", "http"]},
            "command": {"type": ["string", "null"], "default": None}, "args": {"type": "array", "items": {"type": "string"}, "default": []},
            "url": {"type": ["string", "null"], "default": None}, "env": {"type": "object", "default": {}},
            "allowed_tools": {"type": "array", "items": {"type": "string"}, "default": []}, "enabled": {"type": "boolean", "default": True},
        }, ["name", "transport"]), self.mcp.create_server, gate="mcp", risk="write")
        self.register("update_mcp_server", "Update an MCP server name, enabled state, or explicit discovered-tool allowlist.", object_schema({
            "server_id": {"type": "string"}, "name": {"type": ["string", "null"], "default": None},
            "allowed_tools": {"type": ["array", "null"], "items": {"type": "string"}, "default": None},
            "enabled": {"type": ["boolean", "null"], "default": None},
        }, ["server_id"]), self.mcp.update_server, gate="mcp", risk="write")
        self.register("discover_mcp_tools", "Start an approved MCP server session and discover its available tools.", object_schema({
            "server_id": {"type": "string"},
        }, ["server_id"]), self.mcp.discover, gate="mcp", risk="external")
        self.register("call_mcp_tool", "Call one explicitly allow-listed tool on a configured MCP server.", object_schema({
            "server_id": {"type": "string"}, "tool_name": {"type": "string"}, "arguments": {"type": "object", "default": {}},
        }, ["server_id", "tool_name"]), self.mcp.call_tool, gate="mcp", risk="external")
        self.register("observe_screen", "Capture the current desktop or a bounded region and pass the image back to the vision model before acting.", object_schema({
            "screenshot_name": {"type": "string", "default": "screen-observation.png"},
            "region": {"type": ["array", "null"], "items": {"type": "integer"}, "default": None},
            "include_image": {"type": "boolean", "default": True},
        }), self.desktop.observe, gate="desktop", risk="desktop")

    def _analyze_goal(self, objective: str, constraints: list[str] | None = None) -> dict[str, Any]:
        return {"ok": True, "contract": self.cognitive.derive_contract(objective, constraints).to_dict()}

    def _remember(self, key: str, value: str) -> dict[str, Any]:
        self.db.upsert_memory(key, value)
        self.db.audit("memory.saved", f"Saved memory {key}")
        return {"ok": True, "key": key}

    def _list_memories(self) -> dict[str, Any]:
        return {"ok": True, "memories": self.db.list_memories()}

    def _list_projects(self, include_archived: bool = False) -> dict[str, Any]:
        return {"ok": True, "projects": self.db.list_projects(include_archived)}

    def _create_project(self, name: str, description: str = "", root_path: str = ".") -> dict[str, Any]:
        self.fs.resolve(root_path)
        return {"ok": True, "project": self.db.create_project(name, description, root_path)}

    def _create_task(self, project_id: str, title: str, details: str = "", priority: str = "normal", dependencies: list[str] | None = None) -> dict[str, Any]:
        if not self.db.get_project(project_id):
            return {"ok": False, "error": "Project not found"}
        return {"ok": True, "task": self.db.create_task(project_id, title, details, priority, dependencies)}

    def _list_tasks(self, project_id: str, status: str | None = None) -> dict[str, Any]:
        return {"ok": True, "tasks": self.db.list_tasks(project_id, status)}

    def _update_task(self, task_id: str, status: str | None = None, priority: str | None = None, details: str | None = None, result: dict[str, Any] | None = None) -> dict[str, Any]:
        values = {"status": status, "priority": priority, "details": details, "result": result}
        task = self.db.update_task(task_id, values)
        return {"ok": bool(task), "task": task} if task else {"ok": False, "error": "Task not found"}

    def _gate_error(self, registered: RegisteredTool, permissions: dict[str, Any]) -> str | None:
        gate_map = {
            "commands": ("allow_commands", "Command execution"),
            "web": ("allow_web", "Internet access"),
            "images": ("allow_images", "Local image generation"),
            "browser": ("allow_browser", "Browser automation"),
            "desktop": ("allow_desktop", "Desktop automation"),
            "voice": ("allow_voice", "Voice tools"),
            "connectors": ("allow_connectors", "Connectors"),
            "mcp": ("allow_mcp", "MCP integrations"),
            "self_improvement": ("allow_self_improvement", "Capability self-improvement"),
        }
        if registered.gate in gate_map:
            key, label = gate_map[registered.gate]
            if not permissions.get(key, False):
                return f"{label} is disabled in DPN AI Settings."
        return None

    async def _invoke(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        registered = self.tools.get(name)
        if not registered:
            return {"ok": False, "error": f"Unknown tool: {name}"}
        started = time.monotonic()
        try:
            result = registered.function(**arguments)
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, dict):
                result = {"ok": True, "result": result}
        except TypeError as exc:
            result = {"ok": False, "error": f"Invalid tool arguments: {exc}"}
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": f"Tool failed: {type(exc).__name__}: {exc}"}
        result.setdefault("elapsed_ms", int((time.monotonic() - started) * 1000))
        return result

    @staticmethod
    def _redact_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in arguments.items():
            if key.lower() in {"password", "token", "secret", "api_key", "authorization"}:
                output[key] = "[redacted]"
            elif key in {"content", "old_text", "new_text"} and isinstance(value, str):
                output[key] = f"[text omitted: {len(value)} characters]"
            elif isinstance(value, str) and len(value) > 1000:
                output[key] = value[:1000] + "…"
            else:
                output[key] = value
        return output

    async def execute(self, name: str, arguments: dict[str, Any], permissions: dict[str, Any]) -> dict[str, Any]:
        registered = self.tools.get(name)
        if not registered:
            return {"ok": False, "error": f"Unknown tool: {name}"}
        gate_error = self._gate_error(registered, permissions)
        if gate_error:
            return {"ok": False, "error": gate_error}
        mode = permissions.get("approval_mode", "standard")
        if mode == "safe" and registered.risk in {"execute", "destructive", "external", "desktop"}:
            return {"ok": False, "error": f"{name} is blocked by Safe approval mode."}
        if mode == "standard" and registered.risk in {"destructive", "external", "desktop"}:
            approval = self.db.create_approval(
                name, self._redact_arguments(arguments), registered.risk,
                f"{name} has {registered.risk} side effects and requires a human decision in Standard mode.",
                permissions.get("run_id"),
            )
            # Keep original arguments only in the encrypted/local database trace where possible.
            with self.db.connect() as connection:
                import json
                connection.execute("UPDATE approval_requests SET arguments_json=? WHERE id=?", (json.dumps(arguments, ensure_ascii=False, default=str), approval["id"]))
            return {"ok": False, "approval_required": True, "approval_id": approval["id"], "risk": registered.risk,
                    "error": f"Approval required for {name}. Open the Approval Inbox."}
        result = await self._invoke(name, arguments)
        self.db.audit("tool.executed", f"{name}: {'ok' if result.get('ok') else 'failed'}",
                      {"tool": name, "arguments": self._redact_arguments(arguments), "ok": bool(result.get("ok")),
                       "elapsed_ms": result.get("elapsed_ms", 0)}, actor="agent")
        return result

    async def execute_approval(self, approval_id: str) -> dict[str, Any]:
        approval = self.db.get_approval(approval_id)
        if not approval:
            return {"ok": False, "error": "Approval not found"}
        if approval.get("status") != "approved":
            return {"ok": False, "error": "Approval must be approved before execution"}
        result = await self._invoke(approval["tool_name"], approval.get("arguments", {}))
        self.db.resolve_approval(approval_id, "executed" if result.get("ok") else "failed", result)
        self.db.audit("tool.approved_execution", f"Executed approved tool {approval['tool_name']}",
                      {"approval_id": approval_id, "ok": bool(result.get("ok"))}, actor="user")
        return result