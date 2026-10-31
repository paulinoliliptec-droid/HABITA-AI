"""Meta Model API image editing (Muse Image), for HR-012 concepts.

``POST {base}/images/edits`` (OpenAI-compatible multipart: model, prompt, image, n, response_format=b64_json), answered
with ``data[0].b64_json``. A URL answer is refused: the backend never fetches an address chosen by a response. The
answer is read as a stream and refused past a size limit, so it is never fully buffered. The key is sent only in the
header and never logged; neither is the image."""

import base64
import json
import logging
import re
import time

import httpx

from app.core.errors import ServiceNotConfiguredError, UpstreamServiceError

logger = logging.getLogger(__name__)
_UNAVAILABLE = "The image service is temporarily unavailable. Please try again."
#: A 20 MB image in base64 plus the JSON around it.
MAX_RESPONSE = 28 * 1024 * 1024


def _safe(value) -> str:
    """An error code or type only if it looks like one; anything else might carry request content."""
    text = str(value) if isinstance(value, (str, int)) else ""
    return text if re.fullmatch(r"[A-Za-z0-9_.\-]{1,40}", text) else "-"


class MetaImageEditor:
    def __init__(self, http: httpx.AsyncClient, *, api_key: str | None, base_url: str, model_id: str) -> None:
        if model_id.endswith("-contributor"):
            raise ValueError("Contributor-mode Meta models may train on user data and are not allowed.")
        self._http, self._key, self.model_id = http, api_key, model_id
        self._url = base_url.rstrip("/") + "/images/edits"

    async def edit(self, image: bytes, prompt: str) -> bytes:
        if not self._key:
            raise ServiceNotConfiguredError("Concepts are not configured on the server (META_API_KEY is missing).")
        started = time.monotonic()
        body = bytearray()
        try:
            async with self._http.stream(
                    "POST", self._url, headers={"Authorization": f"Bearer {self._key}"},
                    data={"model": self.model_id, "prompt": prompt, "n": "1", "response_format": "b64_json"},
                    files={"image": ("photo.jpg", image, "image/jpeg")}) as r:
                status = r.status_code
                async for chunk in r.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_RESPONSE:
                        raise UpstreamServiceError(_UNAVAILABLE)
        except httpx.TransportError as exc:
            logger.warning("Meta image request failed: %s", type(exc).__name__)
            raise UpstreamServiceError(_UNAVAILABLE) from None
        logger.info("Meta image call model=%s status=%d latency_ms=%d", self.model_id, status,
                    round((time.monotonic() - started) * 1000))
        if status != 200:
            # Only the error's code and type are logged: its message may echo the request.
            try:
                err = json.loads(bytes(body)).get("error") or {}
                fields = [_safe(err.get("code")), _safe(err.get("type"))]
            except (ValueError, AttributeError, RecursionError):
                fields = ["-", "-"]
            logger.warning("Meta image error status=%d code=%s type=%s", status, *fields)
            raise UpstreamServiceError(_UNAVAILABLE)
        try:
            encoded = json.loads(bytes(body))["data"][0]["b64_json"]
            out = base64.b64decode(encoded, validate=True)
        except (ValueError, KeyError, IndexError, TypeError, RecursionError):
            logger.warning("Meta image response failed validation")
            raise UpstreamServiceError(_UNAVAILABLE) from None
        if not out:
            raise UpstreamServiceError(_UNAVAILABLE)
        return out
