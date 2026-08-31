from __future__ import annotations

import copy
from typing import Any

import httpx


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str, timeout: float = 600.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/api/version")
                response.raise_for_status()
                return {"ok": True, **response.json()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    async def list_models(self) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(f"{self.base_url}/api/tags")
        except httpx.ConnectError as exc:
            raise OllamaError("DPN AI cannot reach Ollama. Start the Ollama application or run `ollama serve`.") from exc
        except httpx.TimeoutException as exc:
            raise OllamaError("Ollama did not answer the model-list request before the timeout.") from exc
        if response.status_code >= 400:
            raise OllamaError(f"Ollama returned {response.status_code}: {response.text[:500]}")
        return response.json().get("models", [])

    @classmethod
    def _normalize_schema_node(cls, value: Any) -> Any:
        """Reduce JSON Schema to the conservative subset accepted by older Ollama builds.

        DPN AI uses richer schemas internally, including nullable ``type`` arrays and
        defaults. Some Ollama versions return HTTP 500 when those are included in a
        tool definition. The model does not need defaults or explicit null unions to
        call a tool, so they are removed at the model boundary only.
        """
        if isinstance(value, list):
            return [cls._normalize_schema_node(item) for item in value]
        if not isinstance(value, dict):
            return value

        output: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"default", "$schema", "examples", "example", "deprecated", "readOnly", "writeOnly"}:
                continue
            if key == "type" and isinstance(item, list):
                concrete = [entry for entry in item if entry != "null"]
                if concrete:
                    output[key] = concrete[0]
                continue
            if key in {"anyOf", "oneOf"} and isinstance(item, list):
                concrete = [entry for entry in item if not (isinstance(entry, dict) and entry.get("type") == "null")]
                if len(concrete) == 1:
                    normalized = cls._normalize_schema_node(concrete[0])
                    if isinstance(normalized, dict):
                        output.update(normalized)
                    continue
            output[key] = cls._normalize_schema_node(item)

        properties = output.get("properties")
        required = output.get("required")
        if isinstance(properties, dict) and isinstance(required, list):
            output["required"] = [name for name in required if name in properties]
        return output

    @classmethod
    def normalize_tools(cls, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        normalized: list[dict[str, Any]] = []
        for raw in tools:
            tool = copy.deepcopy(raw)
            function = tool.get("function") if isinstance(tool, dict) else None
            if not isinstance(function, dict) or not function.get("name"):
                continue
            parameters = function.get("parameters") or {"type": "object", "properties": {}}
            function["parameters"] = cls._normalize_schema_node(parameters)
            normalized.append({"type": "function", "function": function})
        return normalized or None

    async def _post_chat(self, payload: dict[str, Any]) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await client.post(f"{self.base_url}/api/chat", json=payload)
        except httpx.ConnectError as exc:
            raise OllamaError(
                "DPN AI cannot reach Ollama. Start Ollama, then pull a model such as "
                f"`ollama pull {payload.get('model', 'qwen3.5:9b')}`."
            ) from exc
        except httpx.TimeoutException as exc:
            raise OllamaError(
                "Ollama did not finish the response before the timeout. Try a smaller model, disable Thinking, "
                "or increase DPN_MAX_RUN_SECONDS."
            ) from exc
        except httpx.RequestError as exc:
            raise OllamaError(f"The Ollama request failed: {exc}") from exc

    @staticmethod
    def _error_text(response: httpx.Response) -> str:
        text = (response.text or "").strip()
        try:
            payload = response.json()
            if isinstance(payload, dict):
                text = str(payload.get("error") or payload.get("detail") or text)
        except Exception:  # noqa: BLE001
            pass
        return text[:1500] or "No error details were returned."

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        think: bool | str = False,
    ) -> dict[str, Any]:
        normalized_tools = self.normalize_tools(tools)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": "24h",
            "options": {"temperature": 0.25},
        }
        if think not in {False, None, "", "off", "false"}:
            payload["think"] = think
        if normalized_tools:
            payload["tools"] = normalized_tools

        response = await self._post_chat(payload)
        if response.status_code < 400:
            try:
                return response.json()
            except ValueError as exc:
                raise OllamaError("Ollama returned an invalid non-JSON chat response.") from exc

        first_error = self._error_text(response)

        # Compatibility retry: older Ollama/model combinations may reject string
        # thinking levels even though the server itself is otherwise healthy.
        if "think" in payload:
            retry_payload = dict(payload)
            retry_payload.pop("think", None)
            retry = await self._post_chat(retry_payload)
            if retry.status_code < 400:
                try:
                    return retry.json()
                except ValueError as exc:
                    raise OllamaError("Ollama returned invalid JSON after the compatibility retry.") from exc
            retry_error = self._error_text(retry)
            if retry_error and retry_error != first_error:
                first_error = f"{first_error} | retry without Thinking: {retry_error}"

        hint = ""
        lower = first_error.lower()
        if response.status_code == 404 or "model" in lower and any(word in lower for word in ("not found", "missing", "pull")):
            hint = f" Pull the selected model with `ollama pull {model}` or choose an installed model in DPN AI."
        elif response.status_code >= 500:
            hint = " Restart Ollama and update it if possible. DPN AI already retried with a conservative request format."
        raise OllamaError(f"Ollama returned {response.status_code}: {first_error}.{hint}".strip())

    async def warm_model(self, model: str) -> dict[str, Any]:
        """Load a model into Ollama memory and keep it resident for fast first-token latency."""
        payload = {"model": model, "prompt": "", "stream": False, "keep_alive": "24h"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/generate", json=payload)
        except httpx.ConnectError as exc:
            raise OllamaError("DPN AI cannot reach Ollama to warm the intelligence model.") from exc
        except httpx.TimeoutException as exc:
            raise OllamaError("The intelligence model did not finish loading before the timeout.") from exc
        if response.status_code >= 400:
            raise OllamaError(f"Model warm-up failed ({response.status_code}): {self._error_text(response)}")
        result = response.json()
        return {"ok": True, "model": model, "load_duration": result.get("load_duration", 0)}

    async def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        think: bool | str = False,
        on_token=None,
    ) -> dict[str, Any]:
        """Stream Ollama response tokens while returning a normal accumulated response."""
        import inspect
        import json

        normalized_tools = self.normalize_tools(tools)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "keep_alive": "24h",
            "options": {"temperature": 0.25},
        }
        if think not in {False, None, "", "off", "false"}:
            payload["think"] = think
        if normalized_tools:
            payload["tools"] = normalized_tools

        async def emit(value: str) -> None:
            if not value or on_token is None:
                return
            result = on_token(value)
            if inspect.isawaitable(result):
                await result

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                    if response.status_code >= 400:
                        raw = await response.aread()
                        text = raw.decode("utf-8", errors="replace")
                        raise OllamaError(f"Ollama returned {response.status_code}: {text[:1500]}")
                    content_parts: list[str] = []
                    thinking_parts: list[str] = []
                    tool_calls: list[dict[str, Any]] = []
                    final_payload: dict[str, Any] = {}
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        final_payload = chunk
                        message = chunk.get("message") or {}
                        delta = str(message.get("content") or "")
                        if delta:
                            content_parts.append(delta)
                            await emit(delta)
                        thinking = str(message.get("thinking") or "")
                        if thinking:
                            thinking_parts.append(thinking)
                        if message.get("tool_calls"):
                            tool_calls = message.get("tool_calls") or tool_calls
                    message = {
                        "role": "assistant",
                        "content": "".join(content_parts),
                    }
                    if thinking_parts:
                        message["thinking"] = "".join(thinking_parts)
                    if tool_calls:
                        message["tool_calls"] = tool_calls
                    final_payload["message"] = message
                    final_payload["done"] = True
                    return final_payload
        except httpx.ConnectError as exc:
            raise OllamaError("DPN AI cannot reach Ollama. Start Ollama or run `ollama serve`.") from exc
        except httpx.TimeoutException as exc:
            raise OllamaError("The streamed Ollama response timed out.") from exc
        except httpx.RequestError as exc:
            raise OllamaError(f"The streamed Ollama request failed: {exc}") from exc

    async def embed(self, model: str, inputs: list[str]) -> list[list[float]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": model, "input": inputs, "truncate": True},
                )
        except httpx.ConnectError as exc:
            raise OllamaError("DPN AI cannot reach Ollama for semantic memory embeddings.") from exc
        except httpx.TimeoutException as exc:
            raise OllamaError("Ollama embedding generation timed out.") from exc
        if response.status_code >= 400:
            raise OllamaError(f"Embedding failed ({response.status_code}): {self._error_text(response)}")
        return response.json().get("embeddings", [])

    async def pull_model(self, model: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                response = await client.post(
                    f"{self.base_url}/api/pull",
                    json={"model": model, "stream": False},
                )
        except httpx.ConnectError as exc:
            raise OllamaError("DPN AI cannot reach Ollama to download the model.") from exc
        if response.status_code >= 400:
            raise OllamaError(f"Model pull failed ({response.status_code}): {self._error_text(response)}")
        return response.json()