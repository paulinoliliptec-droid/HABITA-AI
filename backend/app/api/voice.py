"""Dictation: a short recording in, text out, for the user to review before sending (owner, 2026-11-01)."""

import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.services.dictation import MAX_BYTES, InvalidAudioError

router = APIRouter(prefix="/api/voice", tags=["voice"])
BODY_SECONDS = 30


class Transcript(BaseModel):
    text: str
    model_id: str


async def _body(request: Request) -> bytes:
    data = bytearray()
    try:
        async with asyncio.timeout(BODY_SECONDS):
            async for chunk in request.stream():
                data += chunk
                if len(data) > MAX_BYTES:
                    raise InvalidAudioError("Dictation can be at most 60 seconds long.")
    except TimeoutError:
        raise InvalidAudioError("The recording took too long to arrive. Please try again.") from None
    return bytes(data)


def client_address(request: Request) -> str:
    """The caller's address. On Cloud Run the front end appends the client address as the last X-Forwarded-For entry,
    so a caller can add entries but can't replace that one; locally the socket address is used."""
    forwarded = request.headers.get("x-forwarded-for", "")
    last = forwarded.split(",")[-1].strip() if forwarded else ""
    return last or (request.client.host if request.client else "unknown")


@router.post("/transcribe", response_model=Transcript)
async def transcribe(request: Request) -> Transcript:
    """The recording is the raw body (16-bit mono WAV). Nothing is kept; the text only goes back to the box."""
    dictation = request.app.state.dictation
    async with dictation.admit():  # the rate is taken before the body is read
        text = await dictation.transcribe_admitted(await _body(request), client_address(request))
    return Transcript(text=text, model_id=dictation.model_id)
