from __future__ import annotations

import base64
import ipaddress
import json
import re
import socket
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.db import Database
from app.ollama_client import OllamaClient, OllamaError
from app.vault import SecretVault


class ModelGateway:
    """Route DPN AI requests across Ollama and OpenAI-compatible endpoints.

    Bare model names use the configured default provider. Prefixes may be used
    explicitly: ``ollama:model`` or ``compatible:model``. Compatible endpoints
    include local servers such as LM Studio, vLLM, llama.cpp, LocalAI, and other
    services that implement the OpenAI chat-completions contract.
    """

    def __init__(self, settings: Settings, db: Database, vault: SecretVault, timeout: float = 600.0):
        self.settings = settings
        self.db = db
        self.vault = vault
        self.timeout = timeout
        self.ollama = OllamaClient(settings.ollama_url, timeout=timeout)
        self._best_model_cache: tuple[float, str] | None = None

    def _config(self) -> dict[str, Any]:
        stored = self.db.all_settings()
        return {
            "default_provider": str(stored.get("default_provider", self.settings.default_provider) or "ollama"),
            "compatible_api_url": str(stored.get("compatible_api_url", self.settings.compatible_api_url) or "").rstrip("/"),
            "compatible_api_secret": str(stored.get("compatible_api_secret", self.settings.compatible_api_secret) or "MODEL_PROVIDER_KEY"),
            "allow_external_models": bool(stored.get("allow_external_models", self.settings.allow_external_models_default)),
        }

    @staticmethod
    def _is_local_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
            if host.lower() in {"localhost", "host.docker.internal"}:
                return True
            try:
                return ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
            except ValueError:
                addresses = socket.getaddrinfo(host, parsed.port or 80, type=socket.SOCK_STREAM)
                return bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_private or ipaddress.ip_address(item[4][0]).is_loopback for item in addresses)
        except Exception:
            return False

    @staticmethod
    def _api_root(url: str) -> str:
        value = url.rstrip("/")
        return value if value.lower().endswith("/v1") else f"{value}/v1"

    def _compatible_headers(self) -> dict[str, str]:
        config = self._config()
        headers = {"Content-Type": "application/json"}
        try:
            secret = self.vault.get_value(config["compatible_api_secret"])
        except KeyError:
            secret = ""
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        return headers

    def _ensure_compatible_allowed(self) -> str:
        config = self._config()
        url = config["compatible_api_url"]
        if not url:
            raise OllamaError("No OpenAI-compatible model endpoint is configured.")
        if not self._is_local_url(url) and not config["allow_external_models"]:
            raise OllamaError("External model endpoints are disabled. Enable them explicitly in DPN AI Settings.")
        return url

    @staticmethod
    def _parameter_billions(item: dict[str, Any]) -> float:
        details = item.get("details") or {}
        raw = str(details.get("parameter_size") or item.get("parameter_size") or "").strip().upper()
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([BM])", raw)
        if match:
            value = float(match.group(1))
            return value if match.group(2) == "B" else value / 1000.0
        size = float(item.get("size") or 0)
        # Quantized model files are usually roughly 0.45-0.8 bytes per parameter.
        return max(0.0, size / 650_000_000.0)

    @classmethod
    def _model_score(cls, item: dict[str, Any], profile: str = "auto", require_vision: bool = False) -> float:
        name = str(item.get("name") or item.get("model") or "").lower()
        if not name or any(token in name for token in ("embed", "embedding", "nomic-embed", "bge-", "snowflake-arctic-embed")):
            return -1.0
        params = cls._parameter_billions(item)
        score = params * 100.0 + min(float(item.get("size") or 0) / 1_000_000_000.0, 100.0)
        # Prefer newer tool-capable model families when parameter counts are close.
        family_bonus = {
            "qwen3.5": 45, "qwen3": 35, "llama4": 42, "gemma3": 28, "mistral-small": 30,
            "deepseek-r1": 26, "command-r": 22, "phi4": 18, "qwen2.5": 15,
        }
        score += max((bonus for token, bonus in family_bonus.items() if token in name), default=0)
        vision_tokens = ("vision", "vl", "llava", "gemma3", "llama4", "qwen3.5")
        if require_vision:
            score += 80 if any(token in name for token in vision_tokens) else -120
        if profile in {"software", "fivem", "data", "science"} and any(token in name for token in ("coder", "code", "qwen3", "qwen2.5")):
            score += 20
        return score

    async def select_best_model(
        self,
        requested: str | None,
        *,
        profile: str = "auto",
        require_vision: bool = False,
        intelligence_mode: str = "maximum",
        fallback: str = "",
    ) -> str:
        value = (requested or "").strip()
        auto_values = {"", "auto", "auto:max", "__maximum__", "maximum"}
        if value.lower() not in auto_values:
            return value
        if intelligence_mode == "manual" and fallback:
            return fallback
        now = time.monotonic()
        if self._best_model_cache and now - self._best_model_cache[0] < 60 and not require_vision:
            return self._best_model_cache[1]
        try:
            models = await self.list_models()
        except Exception:
            return fallback or self.settings.default_model
        default_provider = self._config()["default_provider"]
        candidates = [item for item in models if item.get("provider") == default_provider]
        if not candidates:
            candidates = models
        ranked = sorted(candidates, key=lambda item: self._model_score(item, profile, require_vision), reverse=True)
        ranked = [item for item in ranked if self._model_score(item, profile, require_vision) >= 0]
        if not ranked:
            return fallback or self.settings.default_model
        chosen = str(ranked[0].get("name") or ranked[0].get("model") or fallback or self.settings.default_model)
        if not require_vision:
            self._best_model_cache = (now, chosen)
        return chosen

    def resolve_model(self, model: str) -> tuple[str, str]:
        value = (model or "").strip()
        if value.startswith("ollama:"):
            return "ollama", value.split(":", 1)[1]
        if value.startswith("compatible:"):
            return "compatible", value.split(":", 1)[1]
        if value.startswith("openai:"):
            return "compatible", value.split(":", 1)[1]
        return self._config()["default_provider"], value

    async def warm_best_model(self, fallback: str = "", profile: str = "auto") -> dict[str, Any]:
        model = await self.select_best_model(
            "__maximum__", profile=profile, intelligence_mode="maximum", fallback=fallback or self.settings.default_model
        )
        provider, provider_model = self.resolve_model(model)
        if provider != "ollama":
            return {"ok": True, "model": model, "provider": provider, "warmed": False, "reason": "Provider manages its own model residency."}
        result = await self.ollama.warm_model(provider_model)
        return {**result, "provider": "ollama", "warmed": True}

    async def health(self) -> dict[str, Any]:
        ollama_health = await self.ollama.health()
        compatible: dict[str, Any] = {"configured": bool(self._config()["compatible_api_url"]), "ok": False}
        if compatible["configured"]:
            try:
                url = self._ensure_compatible_allowed()
                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.get(f"{self._api_root(url)}/models", headers=self._compatible_headers())
                compatible.update({"ok": response.status_code < 400, "status_code": response.status_code})
                if response.status_code >= 400:
                    compatible["error"] = response.text[:500]
            except Exception as exc:  # noqa: BLE001
                compatible["error"] = str(exc)
        return {
            "ok": bool(ollama_health.get("ok") or compatible.get("ok")),
            "default_provider": self._config()["default_provider"],
            "ollama": ollama_health,
            "compatible": compatible,
        }

    async def list_models(self) -> list[dict[str, Any]]:
        models: list[dict[str, Any]] = []
        try:
            for item in await self.ollama.list_models():
                models.append({**item, "name": item.get("name") or item.get("model"), "provider": "ollama"})
        except Exception:
            pass
        if self._config()["compatible_api_url"]:
            try:
                url = self._ensure_compatible_allowed()
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.get(f"{self._api_root(url)}/models", headers=self._compatible_headers())
                if response.status_code < 400:
                    for item in response.json().get("data", []):
                        model_id = str(item.get("id") or "").strip()
                        if model_id:
                            models.append({"name": f"compatible:{model_id}", "model": model_id, "provider": "compatible", "details": item})
            except Exception:
                pass
        return models

    @staticmethod
    def _compatible_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for message in messages:
            entry = {key: value for key, value in message.items() if key in {"role", "content", "name", "tool_call_id", "tool_calls"}}
            images = message.get("images") or []
            if images:
                content: list[dict[str, Any]] = [{"type": "text", "text": str(message.get("content") or "") }]
                for image in images:
                    if isinstance(image, str):
                        if image.startswith("data:"):
                            data_url = image
                        else:
                            data_url = f"data:image/png;base64,{image}"
                        content.append({"type": "image_url", "image_url": {"url": data_url}})
                entry["content"] = content
            output.append(entry)
        return output

    @staticmethod
    def _normalize_compatible_response(payload: dict[str, Any], requested_model: str) -> dict[str, Any]:
        choices = payload.get("choices") or []
        if not choices:
            raise OllamaError("Compatible model endpoint returned no choices.")
        message = choices[0].get("message") or {}
        tool_calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            raw_arguments = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            except json.JSONDecodeError:
                arguments = {"raw": raw_arguments}
            tool_calls.append({
                "id": call.get("id"),
                "type": "function",
                "function": {"name": function.get("name"), "arguments": arguments},
            })
        normalized_message = {"role": message.get("role", "assistant"), "content": message.get("content") or ""}
        if tool_calls:
            normalized_message["tool_calls"] = tool_calls
        return {
            "model": payload.get("model") or requested_model,
            "message": normalized_message,
            "done": True,
            "provider": "compatible",
            "usage": payload.get("usage") or {},
            "raw_id": payload.get("id"),
        }

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        think: bool | str = False,
    ) -> dict[str, Any]:
        provider, provider_model = self.resolve_model(model)
        if provider == "ollama":
            return await self.ollama.chat(model=provider_model, messages=messages, tools=tools, think=think)
        if provider != "compatible":
            raise OllamaError(f"Unsupported model provider: {provider}")
        url = self._ensure_compatible_allowed()
        payload: dict[str, Any] = {
            "model": provider_model,
            "messages": self._compatible_messages(messages),
            "temperature": 0.25,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self._api_root(url)}/chat/completions", headers=self._compatible_headers(), json=payload)
        except httpx.ConnectError as exc:
            raise OllamaError("DPN AI cannot reach the configured OpenAI-compatible model server.") from exc
        if response.status_code >= 400:
            raise OllamaError(f"Compatible model endpoint returned {response.status_code}: {response.text[:1000]}")
        return self._normalize_compatible_response(response.json(), provider_model)

    async def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        think: bool | str = False,
        on_token=None,
    ) -> dict[str, Any]:
        provider, provider_model = self.resolve_model(model)
        if provider == "ollama":
            return await self.ollama.chat_stream(
                model=provider_model, messages=messages, tools=tools, think=think, on_token=on_token
            )
        # Compatible providers vary in streaming behavior. Preserve correctness and
        # emit the completed content as one chunk when native streaming is unavailable.
        result = await self.chat(model=model, messages=messages, tools=tools, think=think)
        content = str((result.get("message") or {}).get("content") or "")
        if content and on_token is not None:
            import inspect
            emitted = on_token(content)
            if inspect.isawaitable(emitted):
                await emitted
        return result

    async def embed(self, model: str, inputs: list[str]) -> list[list[float]]:
        provider, provider_model = self.resolve_model(model)
        if provider == "ollama":
            return await self.ollama.embed(provider_model, inputs)
        url = self._ensure_compatible_allowed()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self._api_root(url)}/embeddings",
                headers=self._compatible_headers(),
                json={"model": provider_model, "input": inputs},
            )
        if response.status_code >= 400:
            raise OllamaError(f"Compatible embedding endpoint returned {response.status_code}: {response.text[:1000]}")
        data = sorted(response.json().get("data", []), key=lambda item: item.get("index", 0))
        return [item.get("embedding", []) for item in data]

    async def pull_model(self, model: str) -> dict[str, Any]:
        provider, provider_model = self.resolve_model(model)
        if provider != "ollama":
            raise OllamaError("Only Ollama models can be pulled from inside DPN AI.")
        return await self.ollama.pull_model(provider_model)