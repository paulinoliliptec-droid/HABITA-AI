"""Meta Model API segmentation (SAM 3.1) for the aerial view (owner, 2026-11-01).

``POST {base}/responses`` with model ``sam-3.1`` and one user message holding the image (data URL) and a text prompt
from HABITA's closed list. The answer's output text holds one line per frame, ``<0f>`` then one record per object:
``ID<|box;x1;y1;x2;y2;w;h|><|mask;x=0;y=0;data=HEIGHT,WIDTH,PAYLOAD|>`` with an inclusive box and a mask raster that
covers exactly that box. Masks are decoded with Meta's published decoder (``meta-sam-parser``). Format established by
real calls on 2026-11-01. The key is sent only in the header; neither the image nor the answer is logged."""

import base64
import json
import logging
import re
import time
from dataclasses import dataclass

import httpx
from meta_sam_parser import InvalidSegmentationMaskError, SegmentationMask, decode_mask_to_raster

from app.core.errors import ServiceNotConfiguredError, UpstreamServiceError

logger = logging.getLogger(__name__)
_UNAVAILABLE = "The aerial analysis is temporarily unavailable. Please try again later."
MAX_RESPONSE = 8 * 1024 * 1024
MAX_OBJECTS = 150
#: Decoded pixels per answer: bounds memory and work whatever the answer holds (Codex aerial-r1).
MAX_DECODED = 1_500_000
_RECORD = re.compile(
    r"(?:,)?([0-9]+)<\|box;x1=(-?[0-9]+);y1=(-?[0-9]+);x2=(-?[0-9]+);y2=(-?[0-9]+);w=([0-9]+);h=([0-9]+)\|>"
    r"<\|mask;x=0;y=0;data=([0-9]+),([0-9]+),([!~][^|]+)\|>")


@dataclass(frozen=True)
class Segment:
    left: int
    top: int
    width: int
    height: int
    #: 0/1 per pixel of the box, row by row.
    mask: bytes


def parse(text: str, image_width: int, image_height: int, keep=None) -> list[Segment]:
    """Every object of frame 0 whose box ``keep(left, top, right, bottom)`` accepts (all when None); only those are
    decoded. Anything malformed, out of the image or undecodable makes the whole answer unreadable (fail-closed: a
    garbled answer must not become "nothing found")."""
    out: list[Segment] = []
    line = text.strip()
    if not line:
        return out
    if not line.startswith("<0f>"):
        raise ValueError("unexpected SAM answer")
    body = line[4:]
    pos = 0
    decoded = 0
    while pos < len(body):
        m = _RECORD.match(body, pos)
        if m is None:
            raise ValueError("malformed SAM record")
        pos = m.end()
        x1, y1, x2, y2, w, h, mh, mw = (int(v) for v in m.group(2, 3, 4, 5, 6, 7, 8, 9))
        if (w, h) != (image_width, image_height) or not (0 <= x1 <= x2 < w and 0 <= y1 <= y2 < h):
            raise ValueError("SAM box outside the image")
        if (mw, mh) != (x2 - x1 + 1, y2 - y1 + 1):
            raise ValueError("SAM mask doesn't match its box")
        if keep is not None and not keep(x1, y1, x2 + 1, y2 + 1):
            continue
        decoded += mw * mh
        if decoded > MAX_DECODED or len(out) >= MAX_OBJECTS:
            raise ValueError("SAM answer too large")
        payload = m.group(10)
        try:
            raster = decode_mask_to_raster(SegmentationMask("lossless" if payload.startswith("~") else "one_bit",
                                                            payload, mw, mh))
        except InvalidSegmentationMaskError:
            raise ValueError("undecodable SAM mask") from None
        out.append(Segment(left=x1, top=y1, width=mw, height=mh, mask=raster))
    return out


class MetaSegmenter:
    def __init__(self, http: httpx.AsyncClient, *, api_key: str | None, base_url: str, model_id: str) -> None:
        if model_id.endswith("-contributor"):
            raise ValueError("Contributor-mode Meta models may train on user data and are not allowed.")
        self._http, self._key, self.model_id = http, api_key, model_id
        self._url = base_url.rstrip("/") + "/responses"

    def configured(self) -> bool:
        return bool(self._key)

    async def segment(self, jpeg: bytes, prompt: str, width: int, height: int, keep=None) -> list[Segment]:
        if not self._key:
            raise ServiceNotConfiguredError("The aerial analysis is not configured on the server (META_API_KEY).")
        body = {"model": self.model_id, "input": [{"role": "user", "content": [
            {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()},
            {"type": "input_text", "text": prompt}]}]}
        started = time.monotonic()
        raw = bytearray()
        try:
            async with self._http.stream("POST", self._url, headers={"Authorization": f"Bearer {self._key}"},
                                         json=body) as r:
                status = r.status_code
                async for chunk in r.aiter_bytes():
                    raw += chunk
                    if len(raw) > MAX_RESPONSE:
                        raise UpstreamServiceError(_UNAVAILABLE)
        except httpx.TransportError as exc:
            logger.warning("Meta segmentation request failed: %s", type(exc).__name__)
            raise UpstreamServiceError(_UNAVAILABLE) from None
        logger.info("Meta segmentation call model=%s status=%d latency_ms=%d", self.model_id, status,
                    round((time.monotonic() - started) * 1000))
        if status != 200:
            raise UpstreamServiceError(_UNAVAILABLE)
        try:
            answer = json.loads(bytes(raw))
            parts = [c.get("text") for o in answer.get("output") or [] if o.get("type") == "message"
                     for c in o.get("content") or [] if c.get("type") == "output_text"]
            # Nothing found is an output text that is empty (seen on real calls, 2026-11-01); no output text at all,
            # or a non-text one, is an unreadable answer, never "nothing found" (Codex aerial-r2).
            if not parts or not all(isinstance(p, str) for p in parts):
                raise ValueError("no output text")
            return parse("".join(parts), width, height, keep)
        except (ValueError, AttributeError, TypeError):
            logger.warning("Meta segmentation answer could not be read")
            raise UpstreamServiceError(_UNAVAILABLE) from None
