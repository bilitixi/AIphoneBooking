"""Streaming STT client wrapper.

Deepgram is wired up as the default (§7.1 called for prototyping 2 vendors —
Deepgram is implemented for real below; AssemblyAI is still a stub). This
module defines the interface the rest of the app depends on so swapping
providers doesn't ripple through media_stream.py.
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import websockets

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class Transcriber(ABC):
    """One instance per active call."""

    @abstractmethod
    async def send_audio(self, chunk: bytes) -> None:
        """Feed one inbound audio chunk from the Twilio media stream."""

    @abstractmethod
    async def finalized_transcripts(self) -> AsyncIterator[str]:
        """Yields caller utterances as STT finalizes each one."""

    @abstractmethod
    async def close(self) -> None:
        ...


class DeepgramTranscriber(Transcriber):
    """Streams Twilio's mulaw/8kHz audio straight through to Deepgram's live
    API (no transcoding needed — Deepgram accepts mulaw natively) and
    surfaces each `is_final` result as one caller utterance."""

    _URL = (
        "wss://api.deepgram.com/v1/listen"
        "?encoding=mulaw&sample_rate=8000&channels=1&punctuate=true&model=nova-2"
    )

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._ws: websockets.ClientConnection | None = None
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None

    async def _ensure_connected(self) -> None:
        if self._ws is not None:
            return
        self._ws = await websockets.connect(
            self._URL, additional_headers={"Authorization": f"Token {self._api_key}"}
        )
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                data = json.loads(raw)
                if data.get("type") != "Results":
                    continue
                alternative = data["channel"]["alternatives"][0]
                transcript = alternative.get("transcript", "").strip()
                if transcript and data.get("is_final"):
                    await self._queue.put(transcript)
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception:
            logger.exception("Deepgram read loop failed")

    async def send_audio(self, chunk: bytes) -> None:
        await self._ensure_connected()
        assert self._ws is not None
        await self._ws.send(chunk)

    async def finalized_transcripts(self) -> AsyncIterator[str]:
        while True:
            yield await self._queue.get()

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
        if self._ws is not None:
            try:
                await self._ws.send(json.dumps({"type": "CloseStream"}))
                await self._ws.close()
            except Exception:
                pass


class AssemblyAITranscriber(Transcriber):
    def __init__(self, api_key: str):
        self._api_key = api_key

    async def send_audio(self, chunk: bytes) -> None:
        raise NotImplementedError

    async def finalized_transcripts(self) -> AsyncIterator[str]:
        raise NotImplementedError
        yield  # pragma: no cover

    async def close(self) -> None:
        raise NotImplementedError


def create_transcriber() -> Transcriber:
    settings = get_settings()
    if settings.stt_provider == "deepgram":
        return DeepgramTranscriber(settings.deepgram_api_key)
    if settings.stt_provider == "assemblyai":
        return AssemblyAITranscriber(settings.assemblyai_api_key)
    raise ValueError(f"Unknown STT_PROVIDER: {settings.stt_provider}")
