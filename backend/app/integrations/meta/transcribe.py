"""Meta Model API speech to text (Muse Voice Transcribe), for dictating a question instead of typing it.

``POST {base}/asr/transcribe`` with two multipart parts: ``request`` (JSON: model, audioEncoding "WAV") and ``audio``
(16-bit mono PCM WAV at 16 or 24 kHz), answered with ``{"transcript": …, "audioDurationMs": …}``. The format was
established by a real call on 2026-11-01 (the public docs don't state it). The key is sent only in the header; neither
the audio nor the transcript is ever logged."""

import json
import logging
import re
import time

import httpx

from app.core.errors import ServiceNotConfiguredError, UpstreamServiceError

logger = logging.getLogger(__name__)
_UNAVAILABLE = "The dictation service is temporarily unavailable. Please type your question."
MAX_RESPONSE = 256 * 1024


def _safe(value) -> str:
    text = str(value) if isinstance(value, (str, int)) else ""
    return text if re.fullmatch(r"[A-Za-z0-9_.\-]{1,40}", text) else "-"


class MetaTranscriber:
    def __init__(self, http: httpx.AsyncClient, *, api_key: str | None, base_url: str, model_id: str) -> None:
        if model_id.endswith("-contributor"):
            raise ValueError("Contributor-mode Meta models may train on user data and are not allowed.")
        self._http, self._key, self.model_id = http, api_key, model_id
        self._url = base_url.rstrip("/") + "/asr/transcribe"

    def configured(self) -> bool:
        return bool(self._key)

    async def transcribe(self, wav: bytes) -> str:
        if not self._key:
            raise ServiceNotConfiguredError("Dictation is not configured on the server (META_API_KEY is missing).")
        started = time.monotonic()
        body = bytearray()
        request = json.dumps({"model": self.model_id, "audioEncoding": "WAV"})
        try:
            async with self._http.stream(
                    "POST", self._url, headers={"Authorization": f"Bearer {self._key}"},
                    files={"request": (None, request, "application/json"),
                           "audio": ("dictation.wav", wav, "audio/wav")}) as r:
                status = r.status_code
                async for chunk in r.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_RESPONSE:
                        raise UpstreamServiceError(_UNAVAILABLE)
        except httpx.TransportError as exc:
            logger.warning("Meta transcribe request failed: %s", type(exc).__name__)
            raise UpstreamServiceError(_UNAVAILABLE) from None
        logger.info("Meta transcribe call model=%s status=%d latency_ms=%d", self.model_id, status,
                    round((time.monotonic() - started) * 1000))
        try:
            parsed = json.loads(bytes(body))
        except ValueError:
            parsed = None
        if status != 200:
            err = parsed.get("error") if isinstance(parsed, dict) else None
            err = err if isinstance(err, dict) else {}
            logger.warning("Meta transcribe error status=%d type=%s param=%s", status,
                           _safe(err.get("type")), _safe(err.get("param")))
            raise UpstreamServiceError(_UNAVAILABLE)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("transcript"), str):
            logger.warning("Meta transcribe answer without a transcript")
            raise UpstreamServiceError(_UNAVAILABLE)
        return parsed["transcript"]
