from __future__ import annotations

import inspect
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable, Iterable

from app.model_routing_runtime_v9 import ModelRouteContext, ModelRoutingRuntime
from app.model_routing_v9 import ModelRoutingError


class ModelFailoverError(RuntimeError):
    """Raised when no policy-allowed model can complete a request."""


@dataclass(frozen=True)
class ModelAttempt:
    model: str
    provider: str
    ok: bool
    error: str = ""


@dataclass(frozen=True)
class ModelFailoverResult:
    result: dict[str, Any]
    selected_model: str
    attempts: tuple[ModelAttempt, ...]


ExecuteModel = Callable[[str], dict[str, Any] | Awaitable[dict[str, Any]]]


class ModelFailoverExecutor:
    """Execute a bounded v9 routing decision without weakening remote policy.

    Failures are scoped to the current request. A failed candidate is marked
    unhealthy in a copied inventory and the deterministic router is asked for a
    new decision. The executor never injects a remote candidate or bypasses the
    routing policy to make progress.
    """

    def __init__(self, runtime: ModelRoutingRuntime | None = None, *, max_attempts: int = 4) -> None:
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 8:
            raise ValueError("max_attempts must be an integer between 1 and 8")
        self.runtime = runtime or ModelRoutingRuntime(max_fallbacks=max_attempts - 1)
        self.max_attempts = max_attempts

    @staticmethod
    def _copy_inventory(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return [dict(item) for item in items]

    @staticmethod
    def _mark_unhealthy(items: list[dict[str, Any]], model: str) -> None:
        target = model.strip().lower()
        for item in items:
            name = str(item.get("name") or item.get("model") or "").strip().lower()
            if name == target:
                item["healthy"] = False

    async def execute(
        self,
        items: Iterable[dict[str, Any]],
        context: ModelRouteContext,
        execute_model: ExecuteModel,
        *,
        compatible_is_local: bool = False,
    ) -> ModelFailoverResult:
        inventory = self._copy_inventory(items)
        attempts: list[ModelAttempt] = []
        active_context = context

        for _ in range(self.max_attempts):
            try:
                decision = self.runtime.decide(inventory, active_context, compatible_is_local=compatible_is_local)
            except ModelRoutingError as exc:
                summary = "; ".join(f"{item.model}: {item.error or 'failed'}" for item in attempts)
                detail = f"; routing stopped: {exc}"
                raise ModelFailoverError(
                    f"No policy-allowed model completed the request{': ' + summary if summary else ''}{detail}"
                ) from exc

            selected = decision.selected
            if selected is None:
                break
            try:
                value = execute_model(selected.name)
                result = await value if inspect.isawaitable(value) else value
                if not isinstance(result, dict):
                    raise TypeError("model execution must return a dictionary")
                attempts.append(ModelAttempt(selected.name, selected.provider, True))
                return ModelFailoverResult(result=result, selected_model=selected.name, attempts=tuple(attempts))
            except Exception as exc:  # noqa: BLE001 - boundary records provider failures
                attempts.append(ModelAttempt(selected.name, selected.provider, False, str(exc)[:500]))
                self._mark_unhealthy(inventory, selected.name)
                # Once an explicitly requested model fails, permit only normal
                # policy-selected fallbacks; remote allowance remains unchanged.
                active_context = replace(active_context, requested_model="")

        summary = "; ".join(f"{item.model}: {item.error or 'failed'}" for item in attempts)
        raise ModelFailoverError(f"No policy-allowed model completed the request{': ' + summary if summary else ''}")


__all__ = ["ModelAttempt", "ModelFailoverError", "ModelFailoverExecutor", "ModelFailoverResult"]
