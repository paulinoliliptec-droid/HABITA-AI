"""Dictation: the user speaks a question or an answer and gets text back to review before sending (owner, 2026-11-01).

The text is only ever put into the box the user is typing in; it is never sent anywhere by itself, so a transcription
error can always be corrected. The audio is checked to be a short 16-bit mono PCM WAV, rewritten as a clean file (no
extra chunks), sent to Muse Voice Transcribe and not kept. Spend: a per-process rate and concurrency cap, and a daily
cap per caller and across instances, all taken before the paid call; a call that writes nothing gives the counts back."""

from __future__ import annotations

import hashlib
import hmac
import io
import logging
import re
import wave
from datetime import UTC, datetime

from app.core.errors import AppError, RateLimitedError, ServiceNotConfiguredError, StorageUnavailableError
from app.core.rate_limit import ResolutionLimiter
from app.integrations.maps.static_maps import MemoryDailyUsage

logger = logging.getLogger(__name__)
RATES = (16000, 24000)
MAX_SECONDS = 60
MIN_SECONDS = 0.3
MAX_BYTES = 24000 * 2 * MAX_SECONDS + 4096
MAX_TEXT = 1000
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")


class InvalidAudioError(AppError):
    status_code = 422
    code = "validation_error"


def clean_wav(data: bytes) -> tuple[bytes, float]:
    """The audio as a fresh WAV with only its samples, and its length in seconds; refuses anything else."""
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            channels, width, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            if channels != 1 or width != 2 or rate not in RATES:
                raise InvalidAudioError("The recording must be 16-bit mono at 16 or 24 kHz.")
            seconds = frames / rate
            if seconds > MAX_SECONDS:
                raise InvalidAudioError(f"Dictation can be at most {MAX_SECONDS} seconds long.")
            if seconds < MIN_SECONDS:
                raise InvalidAudioError("The recording is too short.")
            samples = w.readframes(frames)
    except (wave.Error, EOFError):
        raise InvalidAudioError("This is not a recording HABITA can read.") from None
    if len(samples) != frames * 2:
        raise InvalidAudioError("This is not a recording HABITA can read.")
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples)
    return out.getvalue(), seconds


def clean_text(text: str) -> str:
    text = " ".join(_CONTROL.sub(" ", text).split())
    # The transcript sometimes ends "…dois quartos?." or "cozinha..": one mark, never an ellipsis touched.
    text = re.sub(r"([?!])\.+", r"\1", re.sub(r"(?<!\.)\.\.(?!\.)", ".", text))
    return text[:MAX_TEXT]


class Dictation:
    def __init__(self, transcriber, *, limiter: ResolutionLimiter | None = None, usage=None,
                 daily_limit: int = 500, per_caller_daily: int = 30, caller_key: bytes = b"") -> None:
        self._transcriber = transcriber
        self._limiter = limiter or ResolutionLimiter(10, 5, 2)
        self._usage = usage or MemoryDailyUsage()
        self._daily, self._per_caller = daily_limit, per_caller_daily
        self._caller_key = caller_key or b"habita-dictation"

    @property
    def model_id(self) -> str:
        return self._transcriber.model_id

    def admit(self):
        """The per-process rate, before the body is read; returns the concurrency slot the whole request holds."""
        return self._limiter.admit()

    def caller(self, address: str, day: str) -> str:
        """A day-scoped keyed hash of the caller's address: counted per caller, never stored as an address."""
        return hmac.new(self._caller_key, f"{day}|{address}".encode(), hashlib.sha256).hexdigest()[:24]

    async def transcribe_admitted(self, data: bytes, address: str) -> str:
        if not self._transcriber.configured():
            raise ServiceNotConfiguredError("Dictation is not configured on the server (META_API_KEY is missing).")
        wav, _ = clean_wav(data)  # refused before any count is taken
        day = datetime.now(UTC).date().isoformat()
        # One caller can't use up the day for everyone (Codex voice-r1): their own cap first, then the shared one.
        mine = f"{day}:caller:{self.caller(address, day)}"
        taken: list[str] = []
        try:
            if await self._usage.take(mine, self._per_caller) is None:
                raise RateLimitedError("You have reached today's limit for dictation. Please type your question.")
            taken.append(mine)
            if await self._usage.take(day, self._daily) is None:
                raise RateLimitedError("Today's limit for dictation has been reached. Please type your question.")
            taken.append(day)
        except RateLimitedError:
            await self._give_back(taken)
            raise
        except Exception:  # noqa: BLE001 - without a reliable count, spend is not allowed
            await self._give_back(taken)
            raise StorageUnavailableError("Dictation is temporarily unavailable. Please type your question.") from None
        except BaseException:  # cancelled while counting (Codex voice-r2): what was taken goes back
            await self._give_back(taken)
            raise
        try:
            return clean_text(await self._transcriber.transcribe(wav))
        except BaseException:
            # Nothing was written for the user (failure, cancellation): the attempt doesn't count.
            await self._give_back(taken)
            raise

    async def _give_back(self, keys: list[str]) -> None:
        for key in keys:
            try:
                await self._usage.give_back(key)
            except Exception:  # noqa: BLE001 - a lost refund only makes the limit stricter
                logger.warning("Dictation could not give back a count")
