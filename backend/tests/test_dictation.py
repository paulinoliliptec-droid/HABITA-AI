"""Dictation with Muse Voice Transcribe (owner, 2026-11-01): a short recording in, text out for the user to review."""

import io
import json
import logging
import math
import struct
import wave

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.dictation import MAX_SECONDS, clean_text, clean_wav
from tests.permit_fakes import google_handler


def wav(seconds=1.0, rate=16000, channels=1, width=2) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        n = int(seconds * rate)
        frame = lambda i: struct.pack("<h", int(2000 * math.sin(i / 7)))  # noqa: E731
        w.writeframes(b"".join(frame(i) * channels if width == 2 else b"\x80" * channels for i in range(n)))
    return out.getvalue()


class Meta:
    """The Meta API as seen on 2026-11-01: two parts, `request` (JSON) and `audio`."""

    def __init__(self, status=200, body=None):
        self.calls: list[httpx.Request] = []
        self.status, self.body = status, body

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        body = self.body if self.body is not None else {"transcript": "Posso dividir a sala?", "audioDurationMs": 900}
        return httpx.Response(self.status, json=body)


def client_with(meta: Meta, **overrides) -> TestClient:
    values = {"_env_file": None, "google_maps_api_key": "k", "mongodb_uri": None, "app_env": "test",
              "allow_ephemeral_storage": True, "meta_api_key": "secret-meta-key", "dictation_rate_per_minute": 1000,
              "dictation_burst": 1000}
    return TestClient(create_app(Settings(**{**values, **overrides}), http_transport=httpx.MockTransport(google_handler),
                                 meta_transport=httpx.MockTransport(meta)))


def say(client, data: bytes):
    return client.post("/api/voice/transcribe", content=data, headers={"Content-Type": "audio/wav"})


def test_a_recording_becomes_text_with_the_request_meta_expects():
    meta = Meta()
    with client_with(meta) as client:
        res = say(client, wav())
    assert res.status_code == 200 and res.json() == {"text": "Posso dividir a sala?",
                                                     "model_id": "muse-voice-transcribe-1.0"}
    (sent,) = meta.calls
    assert str(sent.url) == "https://api.meta.ai/v1/asr/transcribe"
    assert sent.headers["Authorization"] == "Bearer secret-meta-key"
    body = sent.content
    assert b'name="request"' in body and b'name="audio"' in body
    assert b'{"model": "muse-voice-transcribe-1.0", "audioEncoding": "WAV"}' in body


@pytest.mark.parametrize("data,why", [
    (b"not audio", "can read"),
    (wav(channels=2), "mono"),
    (wav(rate=44100), "16 or 24 kHz"),
    (wav(width=1), "16-bit"),
    (wav(seconds=0.1), "too short"),
])
def test_anything_but_a_short_mono_wav_is_refused_before_any_call(data, why):
    meta = Meta()
    with client_with(meta) as client:
        res = say(client, data)
    assert res.status_code == 422 and why in res.text and meta.calls == []


def test_too_long_is_refused_before_any_call():
    meta = Meta()
    with client_with(meta) as client:
        assert say(client, wav(seconds=MAX_SECONDS + 1)).status_code == 422
        assert say(client, b"x" * (24000 * 2 * MAX_SECONDS + 5000)).status_code == 422
    assert meta.calls == []


def test_the_audio_is_rewritten_without_extra_chunks():
    data = wav()
    tampered = data[:12] + b"LIST\x08\x00\x00\x00evil!!!!" + data[12:]
    tampered = tampered[:4] + struct.pack("<I", len(tampered) - 8) + tampered[8:]
    clean, seconds = clean_wav(tampered)
    assert b"evil" not in clean and seconds == pytest.approx(1.0)


def test_the_daily_cap_counts_only_calls_that_worked():
    meta = Meta(status=500, body={"error": {"type": "server_error"}})
    with client_with(meta, dictation_daily_limit=1) as client:
        assert say(client, wav()).status_code == 502  # failed: the count is given back
        meta.status, meta.body = 200, None
        assert say(client, wav()).status_code == 200
        res = say(client, wav())
    assert res.status_code == 429 and "Today's limit" in res.text and len(meta.calls) == 2


def test_the_rate_limit_comes_before_the_body():
    meta = Meta()
    with client_with(meta, dictation_rate_per_minute=0.001, dictation_burst=1) as client:
        assert say(client, wav()).status_code == 200
        assert say(client, b"anything").status_code == 429


def test_without_a_key_dictation_says_it_is_not_configured():
    meta = Meta()
    with client_with(meta, meta_api_key=None) as client:
        res = say(client, wav())
    assert res.status_code == 503 and meta.calls == []


@pytest.mark.parametrize("body", [{"nothing": 1}, {"transcript": 3}, ["x"]])
def test_an_answer_without_a_transcript_is_an_error(body):
    with client_with(Meta(body=body)) as client:
        assert say(client, wav()).status_code == 502


def test_the_text_is_cleaned_and_bounded():
    assert clean_text("  posso‮ dividir\n a  sala?\x00 ") == "posso dividir a sala?"
    assert len(clean_text("a " * 2000)) == 1000


def test_neither_audio_nor_text_nor_key_reaches_the_logs(caplog):
    caplog.set_level(logging.DEBUG)
    with client_with(Meta(status=400, body={"error": {"type": "invalid_request_error", "message": "Posso dividir"}})) \
            as client:
        say(client, wav())
    with client_with(Meta()) as client:
        say(client, wav())
    logs = " ".join(r.getMessage() for r in caplog.records)
    assert "Posso" not in logs and "secret-meta-key" not in logs and "invalid_request_error" in logs


def test_contributor_models_are_refused():
    from app.integrations.meta.transcribe import MetaTranscriber
    with pytest.raises(ValueError):
        MetaTranscriber(httpx.AsyncClient(), api_key="k", base_url="https://x", model_id="muse-voice-transcribe-1.0-contributor")


def test_the_route_is_documented_without_a_matter_token():
    with client_with(Meta()) as client:
        spec = json.loads(client.get("/openapi.json").text)
    assert "/api/voice/transcribe" in spec["paths"]


def test_one_caller_cannot_use_up_the_day_for_everyone():
    """Codex voice-r1: a per-caller cap before the shared one; the caller is the address Cloud Run appends last."""
    meta = Meta()
    with client_with(meta, dictation_per_caller_daily=2) as client:
        one = {"Content-Type": "audio/wav", "X-Forwarded-For": "1.1.1.1, 9.9.9.9"}
        spoofed = {"Content-Type": "audio/wav", "X-Forwarded-For": "2.2.2.2, 9.9.9.9"}  # same last entry
        other = {"Content-Type": "audio/wav", "X-Forwarded-For": "8.8.8.8"}
        mine = [client.post("/api/voice/transcribe", content=wav(), headers=h).status_code for h in (one, one, spoofed)]
        theirs = client.post("/api/voice/transcribe", content=wav(), headers=other).status_code
    assert mine == [200, 200, 429] and theirs == 200 and len(meta.calls) == 3


def test_a_full_shared_day_gives_the_callers_count_back():
    meta = Meta()
    with client_with(meta, dictation_daily_limit=1, dictation_per_caller_daily=2) as client:
        h = {"Content-Type": "audio/wav", "X-Forwarded-For": "1.1.1.1"}
        codes = [client.post("/api/voice/transcribe", content=wav(), headers=h).status_code for _ in range(3)]
    assert codes == [200, 429, 429] and len(meta.calls) == 1


async def test_a_cancelled_call_gives_the_counts_back():
    import asyncio

    from app.integrations.maps.static_maps import MemoryDailyUsage
    from app.services.dictation import Dictation

    class Slow:
        model_id = "m"

        def configured(self):
            return True

        async def transcribe(self, wav):
            raise asyncio.CancelledError

    usage = MemoryDailyUsage()
    d = Dictation(Slow(), usage=usage, daily_limit=1, per_caller_daily=1)
    for _ in range(2):  # the second attempt would be refused if the first had kept its counts
        with pytest.raises(asyncio.CancelledError):
            await d.transcribe_admitted(wav(), "1.1.1.1")


def test_the_caller_is_never_stored_as_an_address():
    from app.services.dictation import Dictation
    d = Dictation(object(), caller_key=b"k")
    key = d.caller("1.1.1.1", "2026-11-01")
    assert "1.1.1.1" not in key and key != d.caller("1.1.1.1", "2026-11-02") and len(key) == 24


async def test_cancelled_while_counting_gives_the_callers_count_back():
    """Codex voice-r2: a cancellation between the caller's count and the shared one leaves nothing taken."""
    import asyncio

    from app.integrations.maps.static_maps import MemoryDailyUsage
    from app.services.dictation import Dictation

    class Usage(MemoryDailyUsage):
        cancel = True

        async def take(self, day, limit):
            if ":caller:" not in day and self.cancel:
                raise asyncio.CancelledError
            return await super().take(day, limit)

    class Ok:
        model_id = "m"

        def configured(self):
            return True

        async def transcribe(self, wav):
            return "ok"

    usage = Usage()
    d = Dictation(Ok(), usage=usage, daily_limit=5, per_caller_daily=1)
    with pytest.raises(asyncio.CancelledError):
        await d.transcribe_admitted(wav(), "1.1.1.1")
    usage.cancel = False
    assert await d.transcribe_admitted(wav(), "1.1.1.1") == "ok"


def test_afinamentos_a_question_does_not_end_with_a_stray_full_stop():
    from app.services.dictation import clean_text
    assert clean_text("Posso dividir em dois quartos?.") == "Posso dividir em dois quartos?"
    assert clean_text("Tem cozinha..") == "Tem cozinha."
    assert clean_text("Espere...") == "Espere..."
