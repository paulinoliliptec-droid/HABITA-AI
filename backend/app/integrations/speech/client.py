"""ElevenLabs text to speech for the HR-007 voice explanation, with one voice per language.

The router is ``voices``: a language picks its voice, and a language without one is simply not available here. The key
travels in a header and transport errors are never logged, raised or returned. Spend is bounded by a per-process rate
and a daily sentence cap shared by every instance; the hard cap is the ElevenLabs plan itself. A sentence already
synthesised is served from memory and costs nothing. Every failure, a spend bound included, is ``SpeechUnavailable``:
the reader then hears the browser's own voice, so audio can never stop a report or change a result.
"""

import hashlib
import logging
import time
from collections import OrderedDict
from collections.abc import Mapping
from datetime import UTC, datetime

import httpx

from app.core.errors import RateLimitedError
from app.core.rate_limit import TokenBucket
from app.integrations.maps.static_maps import MemoryDailyUsage

logger = logging.getLogger("habita.speech")

SPEECH_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}"
OUTPUT_FORMAT = "mp3_44100_128"


class SpeechUnavailable(Exception):
    """No synthesised audio now: not configured, over a spend bound, or the service failed."""


class ElevenLabsClient:
    def __init__(self, http_client: httpx.AsyncClient, api_key: str | None, voices: Mapping[str, str | None], *,
                 model: str = "eleven_multilingual_v2", timeout_seconds: float = 15.0, rate_per_minute: float = 120,
                 burst: int = 20, daily_limit: int = 1000, cache_bytes: int = 64_000_000, usage=None,
                 today=lambda: datetime.now(UTC).date(), clock=time.monotonic) -> None:
        self._http, self._key, self._model, self._timeout = http_client, api_key, model, timeout_seconds
        self._voices = {lang: voice for lang, voice in voices.items() if voice}
        self._bucket = TokenBucket(rate_per_minute, burst, clock)
        self._daily_limit, self._today = daily_limit, today
        self._usage = usage if usage is not None else MemoryDailyUsage()
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._cached, self._cache_bytes = 0, cache_bytes

    def configured(self, lang: str) -> bool:
        return bool(self._key) and lang in self._voices

    def _remember(self, key: str, audio: bytes) -> None:
        self._cache[key] = audio
        self._cached += len(audio)
        while self._cached > self._cache_bytes:
            self._cached -= len(self._cache.popitem(last=False)[1])

    async def speak(self, text: str, lang: str) -> bytes:
        """MP3 of one sentence, in the voice of its language."""
        if not self.configured(lang):
            raise SpeechUnavailable
        voice = self._voices[lang]
        key = hashlib.sha256(f"{voice}\0{self._model}\0{text}".encode()).hexdigest()
        if (audio := self._cache.get(key)) is not None:
            self._cache.move_to_end(key)
            return audio
        try:
            self._bucket.take()
            admitted = await self._usage.take(self._today().isoformat(), self._daily_limit)
        except RateLimitedError:
            raise SpeechUnavailable from None
        except Exception:  # without a reliable count, spend is not allowed
            logger.warning("speech skipped: the usage counter is unavailable")
            raise SpeechUnavailable from None
        if admitted is None:
            logger.warning("speech skipped: today's limit has been reached")
            raise SpeechUnavailable
        try:
            response = await self._http.post(SPEECH_URL.format(voice=voice), params={"output_format": OUTPUT_FORMAT},
                                             json={"text": text, "model_id": self._model},
                                             headers={"xi-api-key": self._key}, timeout=self._timeout)
        except httpx.HTTPError:
            logger.warning("speech failed: transport error")
            raise SpeechUnavailable from None
        if response.status_code != 200 or not response.content:
            logger.warning("speech failed: HTTP %s", response.status_code)
            raise SpeechUnavailable
        self._remember(key, response.content)
        return response.content
