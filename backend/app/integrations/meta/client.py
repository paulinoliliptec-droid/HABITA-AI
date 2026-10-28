"""Meta Model API client (Chat Completions, OpenAI-compatible).

Documented behaviour this client relies on (dev.meta.ai, checked 2026-10-27):
- ``POST {base}/chat/completions`` with ``Authorization: Bearer <key>``;
- function tools as ``{"type": "function", "function": {name, description, parameters}}``;
  ``tool_choice`` only supports ``"auto"`` (so it is never sent), and the model may
  answer with tool calls or plain content;
- calls return in ``choices[0].message.tool_calls[]`` with ``function.arguments`` as a
  JSON string; results go back as ``{"role": "tool", "tool_call_id", "content"}`` after the
  assistant message that carried the calls;
- structured output via ``response_format = {"type": "json_schema", "json_schema": {name,
  schema, strict}}``, returned as a JSON string in ``message.content``.

The key is sent only in the header and never logged. Each call logs model, latency
and token usage.
"""

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from app.core.errors import ServiceNotConfiguredError, UpstreamServiceError
from app.services.permit.model import ChatResult, ToolCall

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 2
_UNAVAILABLE = "The reasoning service is temporarily unavailable. Please try again."


class MetaChatModel:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        api_key: str | None,
        base_url: str,
        model_id: str,
        reasoning_effort: str | None = None,
    ) -> None:
        if model_id.endswith("-contributor"):
            raise ValueError("Contributor-mode Meta models may train on user data and are not allowed.")
        self._http = http
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/chat/completions"
        self.model_id = model_id
        self._reasoning_effort = reasoning_effort

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
        schema_name: str | None = None,
    ) -> ChatResult:
        if not self._api_key:
            raise ServiceNotConfiguredError(
                "Permit intelligence is not configured on the server (META_API_KEY is missing)."
            )
        body: dict[str, Any] = {"model": self.model_id, "messages": messages}
        if tools:
            body["tools"] = tools
        if response_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name or "result", "schema": response_schema, "strict": True},
            }
        if self._reasoning_effort:
            body["reasoning_effort"] = self._reasoning_effort

        payload = await self._post(body)
        return _parse(payload)

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            started = time.monotonic()
            try:
                response = await self._http.post(self._url, json=body, headers=headers)
            except httpx.TransportError as exc:
                logger.warning("Meta API request failed: %s (attempt %d)", type(exc).__name__, attempt)
            else:
                elapsed_ms = round((time.monotonic() - started) * 1000)
                if response.status_code == 200:
                    try:
                        payload = response.json()
                    except ValueError:
                        logger.warning("Meta API returned a non-JSON body")
                        break
                    usage = payload.get("usage") or {}
                    logger.info(
                        "Meta API call model=%s latency_ms=%d prompt_tokens=%s completion_tokens=%s",
                        self.model_id, elapsed_ms, usage.get("prompt_tokens"), usage.get("completion_tokens"),
                    )
                    return payload
                # Status only: error bodies are not logged (they may echo request content).
                logger.warning("Meta API HTTP %d after %d ms (attempt %d)", response.status_code, elapsed_ms, attempt)
                if response.status_code < 500 and response.status_code != 429:
                    break
            if attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(0.5 * attempt)
        raise UpstreamServiceError(_UNAVAILABLE)


def _parse(payload: dict[str, Any]) -> ChatResult:
    try:
        choice = payload["choices"][0]
        message = choice["message"]
        calls = []
        for call in message.get("tool_calls") or []:
            raw = call["function"].get("arguments") or "{}"
            arguments = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments must be an object")
            calls.append(ToolCall(id=call["id"], name=call["function"]["name"], arguments=arguments))
        return ChatResult(
            content=message.get("content"),
            tool_calls=tuple(calls),
            finish_reason=choice.get("finish_reason"),
            usage=payload.get("usage") or {},
        )
    except (KeyError, IndexError, TypeError, ValueError):
        logger.warning("Meta API response failed validation")
        raise UpstreamServiceError(_UNAVAILABLE) from None
