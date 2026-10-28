"""Provider-neutral reasoning-model contract for the Permit workflow.

HR-002 runs on Meta's Muse Spark (``app.integrations.meta``). Tests use scripted
implementations of the same protocol, so the workflow never depends on a
specific vendor SDK.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ChatResult:
    content: str | None
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


class ReasoningModel(Protocol):
    #: Model identifier, recorded with every agent step.
    model_id: str

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
        schema_name: str | None = None,
    ) -> ChatResult: ...
