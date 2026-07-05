"""Streaming STT client wrapper.

Vendor is undecided (§7.1 of the design doc — prototype latency with both
before committing). This module defines the interface the rest of the app
depends on so swapping providers doesn't ripple through media_stream.py.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.core.config import get_settings


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
    def __init__(self, api_key: str):
        self._api_key = api_key
        # TODO: open Deepgram's streaming websocket connection here once the
        # vendor decision (§7.1) is finalized.

    async def send_audio(self, chunk: bytes) -> None:
        raise NotImplementedError

    async def finalized_transcripts(self) -> AsyncIterator[str]:
        raise NotImplementedError
        yield  # pragma: no cover - makes this an async generator

    async def close(self) -> None:
        raise NotImplementedError


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
