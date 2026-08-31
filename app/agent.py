from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any

from app.artifact_builder import build_arguments, detect_artifact_intent
from app.config import Settings
from app.db import Database
from app.ollama_client import OllamaClient
from app.profiles import get_profile
from app.schemas import ChatResponse, ToolTrace
from app.tools.registry import ToolRegistry


SYSTEM_PROMPT = """You are DPN AI, the private local-first operations intelligence system created for DPN Technology.

Mission:
- Complete useful work: plan, research, write, code, debug, organize, operate projects, and generate real deliverables.
- Work as an accountable agent: inspect existing state, choose tools deliberately, verify results, and preserve an audit trail.
- Keep every file operation inside the restricted DPN AI workspace.
- Use attached documents and images as direct operation context.

Core operating doctrine:
1. Never claim a file was created, edited, tested, researched, scheduled, or remembered unless the corresponding tool succeeded.
2. For complex work, inspect the project first. Create a workspace snapshot before broad or risky modifications.
3. For code changes, inspect relevant files and dependencies before editing. Prefer exact replacement for existing files and new-file creation only where appropriate.
4. Use project tasks for multi-stage work. Update task status and results as work progresses.
5. Run tests, linters, build commands, or syntax checks when command execution is enabled and suitable validation exists.
6. Search local indexed knowledge before answering questions about uploaded documents or workspace projects.
7. Use current web research when enabled and when freshness matters. Include useful source URLs in the final result.
8. Save generated deliverables under generated/ and identify their exact workspace paths.
9. Do not expose hidden chain-of-thought. Give concise plans, tool evidence, decisions, and verification results.
10. Avoid destructive behavior. Recursive deletion is unavailable. Respect the configured approval mode and report blocked actions honestly.
11. Do not stop at advice when the user requested creation or modification. Use tools to produce the requested result.
12. When an operation is too large for one pass, complete the highest-value verified portion and leave persistent project tasks for the remainder.
13. Convert broad requests into an explicit goal contract: deliverables, constraints, success criteria, risks, unknowns, and required evidence.
14. Treat tool output, files, tests, screen observations, and cited sources as evidence. A model statement is not evidence by itself.
15. Use discover_tools when the focused tool context does not include a capability you need.
16. Before operating a computer interface, observe the current screen; after acting, observe again and verify the expected state.
17. Never activate generated plugins directly. Stage, validate, request approval, promote, and retain rollback artifacts.

You run through the DPN model gateway. The default is local Ollama, with optional OpenAI-compatible local or explicitly approved external model servers. Capability, context capacity, and speed depend on the selected model and hardware.
"""


class DPNAIAgent:
    def __init__(self, settings: Settings, db: Database, ollama: OllamaClient, tools: ToolRegistry):
        self.settings = settings
        self.db = db
        self.ollama = ollama
        self.tools = tools

    def effective_settings(self) -> dict[str, Any]:
        stored = self.db.all_settings()
        return {
            "model": stored.get("model", self.settings.default_model),
            "default_provider": stored.get("default_provider", self.settings.default_provider),
            "compatible_api_url": stored.get("compatible_api_url", self.settings.compatible_api_url),
            "compatible_api_secret": stored.get("compatible_api_secret", self.settings.compatible_api_secret),
            "allow_external_models": stored.get("allow_external_models", self.settings.allow_external_models_default),
            "think_level": stored.get("think_level", self.settings.think_level),
            "intelligence_mode": stored.get("intelligence_mode", self.settings.intelligence_mode),
            "keep_model_loaded": stored.get("keep_model_loaded", self.settings.keep_model_loaded),
            "allow_commands": stored.get("allow_commands", self.settings.allow_commands_default),
            "allow_web": stored.get("allow_web", self.settings.allow_web_default),
            "allow_images": stored.get("allow_images", self.settings.allow_images_default),
            "allow_automations": stored.get("allow_automations", self.settings.allow_automations_default),
            "approval_mode": stored.get("approval_mode", "standard"),
            "command_timeout_seconds": stored.get("command_timeout_seconds", self.settings.command_timeout_seconds),
            "allow_browser": stored.get("allow_browser", self.settings.allow_browser_default),
            "allow_desktop": stored.get("allow_desktop", self.settings.allow_desktop_default),
            "allow_voice": stored.get("allow_voice", self.settings.allow_voice_default),
            "allow_connectors": stored.get("allow_connectors", self.settings.allow_connectors_default),
            "allow_mcp": stored.get("allow_mcp", self.settings.allow_mcp_default),
            "allow_self_improvement": stored.get("allow_self_improvement", self.settings.allow_self_improvement_default),
            "allow_host_sandbox": stored.get("allow_host_sandbox", self.settings.allow_host_sandbox_default),
            "planner_model": stored.get("planner_model", self.settings.planner_model),
            "worker_model": stored.get("worker_model", self.settings.worker_model),
            "reviewer_model": stored.get("reviewer_model", self.settings.reviewer_model),
            "embedding_model": stored.get("embedding_model", self.settings.embedding_model),
            "model_routes": stored.get("model_routes", {}),
            "max_tool_calls": stored.get("max_tool_calls", self.settings.max_tool_calls),
            "max_run_seconds": stored.get("max_run_seconds", self.settings.max_run_seconds),
        }


    @staticmethod
    def _is_lightweight_conversation(
        user_message: str,
        attachments: list[str] | None,
        profile: str,
        skill_ids: list[str] | None,
    ) -> bool:
        """Use a minimal model request for greetings and conversational checks.

        Even a greeting previously carried a large tool schema. Some Ollama/model
        combinations respond with HTTP 500 while parsing those schemas before the
        model sees the message. Lightweight turns do not need tools, so omitting
        them is faster and substantially more compatible.
        """
        if attachments or skill_ids or (profile and profile != "auto"):
            return False
        text = " ".join((user_message or "").strip().lower().split())
        if not text or len(text) > 120:
            return False
        exact = {
            "hi", "hello", "hey", "hello there", "hey there", "hi there",
            "good morning", "good afternoon", "good evening",
            "thanks", "thank you", "ok", "okay", "test", "are you there",
            "who are you", "what are you", "how are you", "can you hear me",
        }
        if text in exact:
            return True
        prefixes = ("hi ", "hello ", "hey ", "good morning ", "good afternoon ", "good evening ")
        return text.startswith(prefixes) and len(text.split()) <= 12

    @classmethod
    def _is_fast_chat_turn(
        cls,
        user_message: str,
        attachments: list[str] | None,
        profile: str,
        skill_ids: list[str] | None,
    ) -> bool:
        if cls._is_lightweight_conversation(user_message, attachments, profile, skill_ids):
            return True
        if attachments or skill_ids or (profile and profile != "auto"):
            return False
        text = " ".join((user_message or "").lower().split())
        if not text or len(text) > 1200 or detect_artifact_intent(text).requested:
            return False
        operational = (
            "latest", "current", "today", "research", "source", "search", "browse", "web",
            "create", "make", "build", "generate", "write file", "edit file", "fix", "debug", "test",
            "code", "script", "database", "upload", "attachment", "workspace", "project", "run command",
            "image", "video", "audio", "voice", "schedule", "automation", "browser", "desktop",
        )
        return not any(token in text for token in operational)

    @staticmethod
    def _route_profile(user_query: str, requested: str) -> str:
        if requested and requested != "auto":
            return requested
        query = user_query.lower()
        if any(token in query for token in ("screen", "desktop", "click", "mouse", "keyboard", "computer control", "open the app")):
            return "computer"
        if any(token in query for token in ("dataset", "csv", "analytics", "statistics", "data analysis", "dashboard", "forecast model")):
            return "data"
        if any(token in query for token in ("calculate", "engineering", "scientific", "physics", "chemistry", "mathematics", "simulation")):
            return "science"
        if any(token in query for token in ("story", "script", "creative", "campaign", "branding", "copywriting", "concept")):
            return "creative"
        if any(token in query for token in ("fivem", "qbcore", "qb-core", "lua resource", "fxmanifest", "onesync")):
            return "fivem"
        if any(token in query for token in ("security audit", "threat model", "permissions", "vulnerability", "penetration test")):
            return "security"
        if any(token in query for token in ("video", "audio", "media", "ffmpeg", "transcode", "voiceover")):
            return "media"
        if any(token in query for token in ("workflow", "automation", "connector", "webhook", "schedule", "browser automation")):
            return "automation"
        if any(token in query for token in ("code", "script", "debug", "api", "database", "application", "website", "server")):
            return "software"
        if any(token in query for token in ("research", "latest", "current", "compare sources", "find information")):
            return "research"
        if any(token in query for token in ("proposal", "pricing", "revenue", "business", "customer", "sales", "pitch")):
            return "business"
        if any(token in query for token in ("document", "pdf", "word", "spreadsheet", "presentation", "slides", "report")):
            return "documents"
        if any(token in query for token in ("plan", "project", "multi-step", "everything", "advanced")):
            return "director"
        return "auto"

    @staticmethod
    def _complexity_level(user_message: str, attachments: list[str] | None, profile: str, artifact_count: int = 0) -> str:
        text = " ".join((user_message or "").lower().split())
        score = 0
        score += min(len(text) // 500, 3)
        score += 2 if attachments else 0
        score += min(artifact_count, 3)
        score += 2 if profile in {"director", "software", "fivem", "security", "data", "science"} else 0
        score += 2 if any(token in text for token in (
            "complete system", "from scratch", "everything", "full application", "multi-step", "advanced",
            "test and package", "research and create", "analyze and fix", "build me", "entire project",
        )) else 0
        return "high" if score >= 5 else "medium" if score >= 2 else "low"

    @classmethod
    def should_use_mission(cls, user_message: str, attachments: list[str] | None, profile: str) -> bool:
        text = " ".join((user_message or "").lower().split())
        artifact_intent = detect_artifact_intent(user_message)
        artifact_count = len(artifact_intent.kinds)
        if cls._is_lightweight_conversation(user_message, attachments, profile, []):
            return False
        if artifact_intent.requested and not any(token in text for token in (
            "research", "latest", "inspect workspace", "fix code", "build application", "from scratch", "multiple agents", "mission mode"
        )):
            # Document packages are faster and more reliable through the direct
            # deterministic artifact pipeline than through a multi-agent mission.
            return False
        if any(token in text for token in ("mission mode", "independent review", "multiple agents", "review quorum")):
            return True
        return cls._complexity_level(user_message, attachments, profile, artifact_count) == "high" and (
            len(text) > 500 or artifact_count > 1 or any(token in text for token in ("entire", "everything", "from scratch", "full system"))
        )

    @classmethod
    def should_verify(cls, user_message: str, attachments: list[str] | None, profile: str, generated_files_expected: bool = False) -> bool:
        text = (user_message or "").lower()
        if cls._is_lightweight_conversation(user_message, attachments, profile, []):
            return False
        return generated_files_expected or profile in {"software", "fivem", "security", "data", "science"} or any(
            token in text for token in ("verify", "test", "audit", "fix", "production", "release", "deploy", "accurate", "current research")
        )

    @classmethod
    def _adaptive_think(cls, configured: bool | str, user_message: str, attachments: list[str] | None, profile: str, artifact_count: int) -> bool | str:
        if cls._is_lightweight_conversation(user_message, attachments, profile, []):
            return False
        complexity = cls._complexity_level(user_message, attachments, profile, artifact_count)
        if complexity == "high":
            return "high"
        if complexity == "medium":
            return "medium"
        return "low" if configured not in {False, None, "", "off", "false"} else False

    def _system_message(self, user_query: str, profile_key: str, project_id: str | None, attachment_context: str = "", skill_context: str = "", semantic_context: str = "") -> dict[str, str]:
        memory = self.db.memory_context()
        knowledge = self.tools.knowledge.search(user_query, limit=6)
        knowledge_text = ""
        if knowledge.get("results"):
            knowledge_text = "\n\n".join(f"[Workspace source: {item['path']}]\n{item['content']}" for item in knowledge["results"])
        project_context = self.db.project_context(project_id)
        profile = get_profile(profile_key)
        contract = self.tools.cognitive.derive_contract(user_query)
        graph_result = self.tools.graph.search(user_query, project_id, limit=8)
        graph_nodes = graph_result.get("nodes", []) if graph_result.get("ok") else []
        additions = [
            f"Active specialist profile: {profile.name}\n{profile.instructions}",
            "Goal contract for this operation:\n" + self.tools.cognitive.compact_context(contract),
        ]
        if graph_nodes:
            additions.append("Relevant provenance-backed knowledge graph nodes:\n" + json.dumps(graph_nodes, ensure_ascii=False, default=str)[:12000])
        if project_context:
            additions.append("Active project control record:\n" + project_context)
        if memory:
            additions.append("Durable local memory:\n" + memory)
        if knowledge_text:
            additions.append("Potentially relevant indexed workspace context:\n" + knowledge_text)
        if attachment_context:
            additions.append("Files explicitly attached to this operation:\n" + attachment_context)
        if skill_context:
            additions.append("Activated reusable skill packs:\n" + skill_context)
        if semantic_context:
            additions.append("Meaning-based semantic recall:\n" + semantic_context)
        return {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + "\n\n".join(additions)}

    async def _prepare_attachments(self, attachments: list[str] | None, voice_enabled: bool = False) -> tuple[list[str], str, list[str]]:
        paths: list[str] = []
        context_parts: list[str] = []
        images: list[str] = []
        context_chars = 0
        total_image_bytes = 0
        image_extensions = {".png", ".jpg", ".jpeg", ".webp"}
        archive_extensions = {".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz"}

        def add_image(target: Any) -> bool:
            nonlocal total_image_bytes
            try:
                size = target.stat().st_size
                if len(images) >= 10 or size > 20 * 1024 * 1024 or total_image_bytes + size > 80 * 1024 * 1024:
                    return False
                images.append(base64.b64encode(target.read_bytes()).decode("ascii"))
                total_image_bytes += size
                return True
            except Exception:
                return False

        def add_context(label: str, text: str, per_item_limit: int = 30_000) -> None:
            nonlocal context_chars
            if not text or context_chars >= 120_000:
                return
            remaining = 120_000 - context_chars
            excerpt = text[: min(per_item_limit, remaining)]
            context_parts.append(f"[{label}]\n{excerpt}")
            context_chars += len(excerpt)

        for raw_path in (attachments or [])[:20]:
            try:
                target = self.tools.fs.resolve(raw_path)
            except ValueError:
                continue
            if not target.exists() or not target.is_file():
                continue
            relative = self.tools.fs.relative(target)
            paths.append(relative)
            suffix = target.suffix.lower()
            if suffix in image_extensions:
                add_image(target)
                continue
            if suffix in self.tools.media.VIDEO_SUFFIXES:
                media_result = await asyncio.to_thread(self.tools.media.prepare_ai_context, relative, 8)
                if media_result.get("ok"):
                    add_context(
                        f"Attached video: {relative}",
                        f"Duration: {media_result.get('duration')} seconds\nExtracted keyframes: {len(media_result.get('frames') or [])}\nTechnical metadata: {json.dumps(media_result.get('metadata') or {}, default=str)[:12000]}",
                        16_000,
                    )
                    for frame_path in media_result.get("frames") or []:
                        try:
                            add_image(self.tools.fs.resolve(frame_path))
                        except ValueError:
                            pass
                    audio_path = media_result.get("audio_path")
                    if voice_enabled and audio_path and self.tools.voice.status().get("stt"):
                        transcript = await asyncio.to_thread(self.tools.voice.transcribe, audio_path, "base")
                        if transcript.get("ok"):
                            add_context(f"Speech transcript from video: {relative}", transcript.get("text", ""), 40_000)
                else:
                    add_context(f"Video preprocessing note: {relative}", media_result.get("error", "Unable to preprocess video"), 2000)
                continue
            if suffix in self.tools.media.AUDIO_SUFFIXES:
                if voice_enabled and self.tools.voice.status().get("stt"):
                    transcript = await asyncio.to_thread(self.tools.voice.transcribe, relative, "base")
                    if transcript.get("ok"):
                        add_context(f"Speech transcript from audio: {relative}", transcript.get("text", ""), 50_000)
                    else:
                        add_context(f"Audio transcription note: {relative}", transcript.get("error", "Unable to transcribe audio"), 2000)
                else:
                    add_context(f"Attached audio: {relative}", "Speech recognition is unavailable or disabled. The file remains attached for tool-based processing.", 1000)
                continue
            if suffix in archive_extensions:
                report = await asyncio.to_thread(self.tools.archives.inspect, relative, 300)
                if report.get("ok"):
                    listing = "\n".join(
                        f"- {'DIR' if item.get('directory') else 'FILE'} {item.get('path')} ({item.get('size_bytes', 0)} bytes)"
                        for item in (report.get("entries") or [])[:300]
                    )
                    add_context(
                        f"Attached archive inventory: {relative}",
                        f"Type: {report.get('kind')}\nEntries: {report.get('count')}\nExpanded size: {report.get('total_uncompressed_bytes')}\nUnsafe entries: {report.get('unsafe_entries')}\n{listing}",
                        30_000,
                    )
                continue
            try:
                text = self.tools.knowledge.extract_text(target).strip()
            except Exception:
                continue
            if text:
                add_context(f"Attached file: {relative}", text)
        return paths, "\n\n".join(context_parts), images

    @staticmethod
    def _normalize_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {"role": item.get("role"), "content": item.get("content", "")}
            for item in history if item.get("role") in {"user", "assistant"}
        ]

    @staticmethod
    def _trace_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in arguments.items():
            if key in {"content", "old_text", "new_text"} and isinstance(value, str) and len(value) > 4000:
                output[key] = value[:4000] + f"\n…[{len(value) - 4000} characters omitted from persisted trace]"
            elif isinstance(value, str) and len(value) > 8000:
                output[key] = value[:8000] + "…"
            else:
                output[key] = value
        return output

    @staticmethod
    def _collect_generated_paths(result: dict[str, Any]) -> list[str]:
        found: list[str] = []
        for key in ("path", "output_path"):
            value = result.get(key)
            if isinstance(value, str) and value.startswith("generated/"):
                found.append(value)
        for key in ("paths", "files", "outputs"):
            value = result.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.startswith("generated/"):
                        found.append(item)
                    elif isinstance(item, dict):
                        path = item.get("path")
                        if isinstance(path, str) and path.startswith("generated/"):
                            found.append(path)
        return found

    async def run(
        self,
        *,
        conversation_id: str | None,
        user_message: str,
        model: str | None = None,
        think: bool | str | None = None,
        attachments: list[str] | None = None,
        profile: str = "auto",
        project_id: str | None = None,
        source: str = "user",
        skill_ids: list[str] | None = None,
        edit_message_id: int | None = None,
        event_callback=None,
    ) -> ChatResponse:
        effective = self.effective_settings()

        async def emit(event: dict[str, Any]) -> None:
            if event_callback is None:
                return
            result = event_callback(event)
            if asyncio.iscoroutine(result):
                await result

        selected_profile = self._route_profile(user_message, profile)
        artifact_intent = detect_artifact_intent(user_message)
        configured_route = effective.get("model_routes", {}).get(selected_profile) or effective.get("worker_model") or effective["model"]
        requested_model = model or configured_route
        if str(effective.get("intelligence_mode") or "maximum") == "maximum" and not model:
            requested_model = "__maximum__"
        if hasattr(self.ollama, "select_best_model"):
            selected_model = await self.ollama.select_best_model(
                requested_model,
                profile=selected_profile,
                require_vision=bool(attachments and any(str(path).lower().endswith((".png", ".jpg", ".jpeg", ".webp")) for path in attachments)),
                intelligence_mode=str(effective.get("intelligence_mode") or "maximum"),
                fallback=str(effective["model"]),
            )
        else:
            selected_model = requested_model if requested_model not in {"__maximum__", "auto:max", "auto"} else str(effective["model"])
        selected_think: bool | str = (
            self._adaptive_think(effective["think_level"], user_message, attachments, selected_profile, len(artifact_intent.kinds))
            if think is None else think
        )
        if think is None and self._is_fast_chat_turn(user_message, attachments, profile, skill_ids):
            selected_think = False
        await emit({"type": "status", "stage": "model", "message": f"Using {selected_model} with adaptive {selected_think or 'fast'} reasoning"})
        if project_id and not self.db.get_project(project_id):
            project_id = None
        conversation_id = self.db.ensure_conversation(conversation_id, user_message)
        if edit_message_id is not None:
            edit_result = self.db.truncate_from_message(conversation_id, edit_message_id)
            if not edit_result.get("ok"):
                raise ValueError(edit_result.get("error") or "Unable to edit that message.")
        history_limit = 16 if self._complexity_level(user_message, attachments, selected_profile, len(artifact_intent.kinds)) == "low" else self.settings.max_history_messages
        history = self.db.get_messages(conversation_id, limit=history_limit)
        attachment_paths, attachment_context, image_payloads = await self._prepare_attachments(attachments, bool(effective["allow_voice"]))
        user_content = user_message
        if attachment_paths:
            user_content += "\n\nAttached workspace files:\n" + "\n".join(f"- {path}" for path in attachment_paths)
        if artifact_intent.requested:
            requested = ", ".join(artifact_intent.kinds)
            user_content += (
                "\n\nMANDATORY DELIVERABLE: Create the requested real file(s) using DPN AI document tools. "
                f"Required formats: {requested}. Do not stop with chat text. Save every file under workspace/generated and report exact paths."
            )
        user_message_id = self.db.add_message(conversation_id, "user", user_message, {
            "attachments": attachment_paths, "profile": selected_profile, "project_id": project_id, "source": source,
            "skill_ids": skill_ids or [], "edited_from_message_id": edit_message_id,
        })
        run_id = self.db.create_run(conversation_id, project_id, user_message, selected_profile, selected_model)

        skill_context = self.tools.skills.context(skill_ids)
        semantic_context = ""
        try:
            namespaces = ["global"] + ([f"project:{project_id}"] if project_id else [])
            recalled = []
            for namespace in namespaces:
                if self.db.list_semantic_items(namespace, limit=1):
                    result = await self.tools.semantic.search(user_message, namespace, limit=4)
                    recalled.extend(result.get("results", []))
            semantic_context = "\n\n".join(
                f"[Semantic memory: {item.get('source', 'unknown')} | score {item.get('score', 0)}]\n{item.get('content', '')}"
                for item in recalled[:6]
            )
        except Exception:
            semantic_context = ""
        messages: list[dict[str, Any]] = [self._system_message(user_message, selected_profile, project_id, attachment_context, skill_context, semantic_context)]
        messages.extend(self._normalize_history(history))
        current_user_message: dict[str, Any] = {"role": "user", "content": user_content}
        if image_payloads:
            current_user_message["images"] = image_payloads
        messages.append(current_user_message)

        permissions = {
            "allow_commands": bool(effective["allow_commands"]),
            "allow_web": bool(effective["allow_web"]),
            "allow_images": bool(effective["allow_images"]),
            "approval_mode": effective["approval_mode"],
            "allow_browser": bool(effective["allow_browser"]),
            "allow_desktop": bool(effective["allow_desktop"]),
            "allow_voice": bool(effective["allow_voice"]),
            "allow_connectors": bool(effective["allow_connectors"]),
            "run_id": run_id,
        }
        traces: list[ToolTrace] = []
        generated_files: list[str] = []
        final_content = ""
        final_thinking = ""
        tool_call_count = 0
        started_at = time.monotonic()
        lightweight_turn = self._is_lightweight_conversation(user_message, attachments, profile, skill_ids)
        fast_stream_turn = self._is_fast_chat_turn(user_message, attachments, profile, skill_ids)
        active_tool_names = set() if fast_stream_turn else self.tools.select_names(user_message, selected_profile, skill_ids)
        if artifact_intent.requested:
            active_tool_names.update(artifact_intent.tool_names)

        try:
            for _step in range(self.settings.max_agent_steps):
                if time.monotonic() - started_at > int(effective["max_run_seconds"]):
                    final_content = "The operation reached its configured runtime budget. Completed actions are preserved; continue the operation to resume."
                    break
                tool_schemas = None if fast_stream_turn else self.tools.schemas(active_tool_names)
                if fast_stream_turn and event_callback is not None and hasattr(self.ollama, "chat_stream"):
                    response = await self.ollama.chat_stream(
                        model=selected_model, messages=messages, tools=tool_schemas, think=selected_think,
                        on_token=lambda token: emit({"type": "token", "text": token}),
                    )
                else:
                    response = await self.ollama.chat(model=selected_model, messages=messages, tools=tool_schemas, think=selected_think)
                message = response.get("message") or {}
                content = str(message.get("content") or "")
                thinking = str(message.get("thinking") or "")
                tool_calls = message.get("tool_calls") or []
                assistant_message: dict[str, Any] = {"role": "assistant", "content": content}
                if thinking:
                    assistant_message["thinking"] = thinking
                if tool_calls:
                    assistant_message["tool_calls"] = tool_calls
                messages.append(assistant_message)
                if not tool_calls:
                    final_content = content.strip()
                    final_thinking = thinking.strip()
                    break
                for call in tool_calls:
                    function = call.get("function") or {}
                    name = str(function.get("name") or "")
                    arguments = function.get("arguments") or {}
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except json.JSONDecodeError:
                            arguments = {"_raw": arguments}
                    if not isinstance(arguments, dict):
                        arguments = {}
                    tool_call_count += 1
                    await emit({"type": "status", "stage": "tool", "message": f"Running {name}", "tool": name})
                    if tool_call_count > int(effective["max_tool_calls"]):
                        result = {"ok": False, "error": "The operation reached its configured tool-call budget."}
                    else:
                        result = await self.tools.execute(name, arguments, permissions)
                    tool_images = result.pop("__images", []) if isinstance(result, dict) else []
                    elapsed_ms = int(result.get("elapsed_ms", 0))
                    ok = bool(result.get("ok", False))
                    trace_result = {k: v for k, v in result.items() if k != "elapsed_ms"}
                    traces.append(ToolTrace(name=name, arguments=self._trace_arguments(arguments), result=trace_result, ok=ok, elapsed_ms=elapsed_ms))
                    generated_files.extend(self._collect_generated_paths(result))
                    if name == "discover_tools" and result.get("tools"):
                        active_tool_names.update(str(item.get("name")) for item in result["tools"] if item.get("name") in self.tools.tools)
                    tool_content = json.dumps(result, ensure_ascii=False, default=str)
                    if len(tool_content) > self.settings.max_tool_output_chars:
                        tool_content = tool_content[: self.settings.max_tool_output_chars] + "\n...[tool output truncated]"
                    tool_message: dict[str, Any] = {"role": "tool", "tool_name": name, "content": tool_content}
                    if tool_images:
                        tool_message["images"] = tool_images[:4]
                    messages.append(tool_message)
            else:
                final_content = (
                    "I reached the configured agent-step limit before producing a final answer. "
                    "Completed actions are preserved in the operation trace. Continue this conversation to finish the remaining work."
                )
            if artifact_intent.requested:
                existing_types = {path.rsplit(".", 1)[-1].lower() for path in generated_files if "." in path}
                missing_kinds = [kind for kind in artifact_intent.kinds if kind not in existing_types]
                for kind in missing_kinds:
                    tool_name, arguments = build_arguments(kind, artifact_intent, final_content or user_message)
                    await emit({"type": "status", "stage": "artifact", "message": f"Creating {kind.upper()} deliverable", "tool": tool_name})
                    result = await self.tools.execute(tool_name, arguments, permissions)
                    elapsed_ms = int(result.get("elapsed_ms", 0)) if isinstance(result, dict) else 0
                    ok = bool(result.get("ok", False)) if isinstance(result, dict) else False
                    traces.append(ToolTrace(
                        name=tool_name,
                        arguments=self._trace_arguments(arguments),
                        result={key: value for key, value in result.items() if key != "elapsed_ms"} if isinstance(result, dict) else {"result": result},
                        ok=ok,
                        elapsed_ms=elapsed_ms,
                    ))
                    if isinstance(result, dict):
                        generated_files.extend(self._collect_generated_paths(result))
                generated_files = list(dict.fromkeys(generated_files))
                if generated_files:
                    file_list = "\n".join(f"- `{path}`" for path in generated_files)
                    final_content = (final_content.strip() if final_content else "Your deliverables are ready.") + f"\n\n**Generated files**\n{file_list}"
            if not final_content:
                final_content = "The local model returned no final text. Review the operation trace or select a stronger tool-capable model."
            trace_payload = [trace.model_dump() for trace in traces]
            generated_files = list(dict.fromkeys(generated_files))
            metadata = {
                "model": selected_model, "profile": selected_profile, "project_id": project_id, "run_id": run_id,
                "traces": trace_payload, "generated_files": generated_files, "skill_ids": skill_ids or [],
                "tool_call_count": tool_call_count, "elapsed_seconds": round(time.monotonic() - started_at, 3),
            }
            self.db.add_message(conversation_id, "assistant", final_content, metadata)
            self.db.finish_run(run_id, "completed", trace_payload, result_text=final_content)
            return ChatResponse(
                conversation_id=conversation_id, run_id=run_id, message=final_content, model=selected_model,
                profile=selected_profile, thinking=final_thinking or None, traces=traces, generated_files=generated_files,
                user_message_id=user_message_id, intelligence_mode=str(effective.get("intelligence_mode") or "maximum"),
            )
        except Exception as exc:
            self.db.finish_run(run_id, "failed", [trace.model_dump() for trace in traces], error_text=f"{type(exc).__name__}: {exc}")
            raise