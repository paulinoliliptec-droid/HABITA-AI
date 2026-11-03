"""A protection layer for the reasoning model (owner, afinamentos 2026-11-01/02): when Meta's Muse Spark API is
unavailable, open-weight models served behind OpenAI-compatible endpoints answer instead, in order: Modal (vLLM),
then Baseten.

What does not change: every draft, from any model, goes through the same deterministic MU-9 verifier and final gate;
the model review can still only make a verdict stricter. Only an *unavailable* model (``UpstreamUnavailableError``:
a timeout, a transport error, a 5xx or a 429 after retries) passes the call on; a refused (4xx) or malformed answer
does not, so the chain is never a way around a refusal.

Each answer records which model gave it: ``model_id`` reads the model that answered the last call in the current task
(a context variable, so concurrent requests never mix), and the workflow and the verifier store ``model_id`` right
after each call.
"""

import logging
from contextvars import ContextVar
from typing import Any

from app.core.errors import UpstreamUnavailableError
from app.services.permit.model import ChatResult, ReasoningModel

logger = logging.getLogger(__name__)

# Cloud Run ends a request at 300 s; a fallback that could only answer after that is useless, so it is not wired.
REQUEST_BUDGET_SECONDS = 290.0
_PRIMARY_ATTEMPTS, _RETRY_PAUSE = 2, 0.5


def fallbacks_within_budget(fallbacks: list[ReasoningModel], primary_timeout: float,
                            fallback_timeout: float) -> list[ReasoningModel]:
    """The fallbacks, in order, whose worst case still ends inside the request budget: Muse Spark's two attempts and
    its retry pause, then one attempt per fallback. A timeout setting that leaves no room drops the later ones (an
    error in the logs) instead of promising an answer Cloud Run would cut off."""
    spent = _PRIMARY_ATTEMPTS * primary_timeout + _RETRY_PAUSE
    kept: list[ReasoningModel] = []
    for model in fallbacks:
        if spent + fallback_timeout > REQUEST_BUDGET_SECONDS:
            logger.error("reasoning fallback %s not enabled: worst case %.1f s exceeds the %.0f s request budget",
                         model.model_id, spent + fallback_timeout, REQUEST_BUDGET_SECONDS)
            break
        spent += fallback_timeout
        kept.append(model)
    return kept


_answered_by: ContextVar[str | None] = ContextVar("habita_answered_by", default=None)


class FallbackChatModel:
    def __init__(self, primary: ReasoningModel, *fallbacks: ReasoningModel) -> None:
        if not fallbacks:
            raise ValueError("at least one fallback model is required")
        self._chain = (primary, *fallbacks)

    @property
    def model_id(self) -> str:
        """The model that answered this task's last call (the primary before any call)."""
        return _answered_by.get() or self._chain[0].model_id

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
        schema_name: str | None = None,
    ) -> ChatResult:
        last = len(self._chain) - 1
        for n, model in enumerate(self._chain):
            try:
                result = await model.chat(messages, tools=tools, response_schema=response_schema,
                                          schema_name=schema_name)
            except UpstreamUnavailableError:
                if n == last:
                    raise
                logger.warning("reasoning model %s unavailable; trying %s", model.model_id,
                               self._chain[n + 1].model_id)
                continue
            _answered_by.set(model.model_id)
            return result
        raise AssertionError("unreachable")
