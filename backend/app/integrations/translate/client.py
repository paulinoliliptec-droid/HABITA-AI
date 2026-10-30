"""Google Cloud Translation (Basic, v2): the bilingual system's machine translation and language detection.

The key travels in a header, so URLs never carry it, and transport errors are never logged, raised or returned: logs
carry counts and HTTP status codes only. Spend is bounded by a per-process rate and a daily request cap shared by every
instance (the same counter as the report maps); the hard cap is the API quota in Google Cloud. Every failure, a spend
bound included, is ``TranslationUnavailable``: callers then show the original text, so translation can never stop a
report or change a result.
"""

import html
import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime

import httpx

from app.core.errors import RateLimitedError
from app.core.rate_limit import TokenBucket
from app.integrations.maps.static_maps import MemoryDailyUsage

logger = logging.getLogger("habita.translate")

TRANSLATE_URL = "https://translation.googleapis.com/language/translate/v2"
DETECT_URL = f"{TRANSLATE_URL}/detect"
MAX_TEXTS, MAX_CHARS = 100, 25_000  # per request; longer batches are split


class TranslationUnavailable(Exception):
    """No translation now: not configured, over a spend bound, or the service failed."""


class GoogleTranslateClient:
    def __init__(self, http_client: httpx.AsyncClient, api_key: str | None, *, timeout_seconds: float = 10.0,
                 rate_per_minute: float = 30, burst: int = 10, daily_limit: int = 500, usage=None,
                 today=lambda: datetime.now(UTC).date(), clock=time.monotonic) -> None:
        self._http, self._key, self._timeout = http_client, api_key, timeout_seconds
        self._bucket = TokenBucket(rate_per_minute, burst)
        self._daily_limit, self._today = daily_limit, today
        self._usage = usage if usage is not None else MemoryDailyUsage()
        self._clock = clock

    @property
    def configured(self) -> bool:
        return bool(self._key)

    async def _post(self, url: str, body: dict) -> dict:
        if not self._key:
            raise TranslationUnavailable
        try:
            self._bucket.take()
            admitted = await self._usage.take(self._today().isoformat(), self._daily_limit)
        except RateLimitedError:
            raise TranslationUnavailable from None
        except Exception:  # without a reliable count, spend is not allowed
            logger.warning("translation skipped: the usage counter is unavailable")
            raise TranslationUnavailable from None
        if admitted is None:
            logger.warning("translation skipped: today's limit has been reached")
            raise TranslationUnavailable
        try:
            response = await self._http.post(url, json=body, headers={"X-Goog-Api-Key": self._key},
                                             timeout=self._timeout)
        except httpx.HTTPError:
            logger.warning("translation failed: transport error")
            raise TranslationUnavailable from None
        if response.status_code != 200:
            logger.warning("translation failed: HTTP %s", response.status_code)
            raise TranslationUnavailable
        try:
            return response.json()["data"]
        except (ValueError, KeyError, TypeError):
            logger.warning("translation failed: malformed response")
            raise TranslationUnavailable from None

    async def translate(self, texts: Sequence[str], target: str) -> list[str]:
        """HTML texts (``<span translate="no">`` keeps a span as it is), from English, in the order given."""
        out: list[str] = []
        batch: list[str] = []
        size = 0
        for text in [*texts, None]:
            if batch and (text is None or len(batch) == MAX_TEXTS or size + len(text) > MAX_CHARS):
                data = await self._post(TRANSLATE_URL, {"q": batch, "source": "en", "target": target, "format": "html"})
                try:
                    translated = [t["translatedText"] for t in data["translations"]]
                except (KeyError, TypeError):
                    raise TranslationUnavailable from None
                if len(translated) != len(batch):
                    raise TranslationUnavailable
                out += translated
                batch, size = [], 0
            if text is not None:
                batch.append(text)
                size += len(text)
        return out

    async def detect(self, text: str) -> str | None:
        """The language code Google is most confident of, or None."""
        data = await self._post(DETECT_URL, {"q": [html.escape(text, quote=False)]})
        try:
            return data["detections"][0][0]["language"]
        except (KeyError, IndexError, TypeError):
            return None
