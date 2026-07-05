"""Streaming TTS client wrapper.

Vendor is undecided (§7.1 — prototype latency with both before committing).
Same rationale as transcriber.py: isolate the vendor behind this interface.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.core.config import get_settings


class Synthesizer(ABC):
    @abstractmethod
    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """Yields audio chunks (mu-law/8kHz, matching Twilio's expected format)
        for the given agent reply text."""


class ElevenLabsSynthesizer(Synthesizer):
    def __init__(self, api_key: str):
        self._api_key = api_key

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        raise NotImplementedError
        yield  # pragma: no cover


class CartesiaSynthesizer(Synthesizer):
    def __init__(self, api_key: str):
        self._api_key = api_key

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        raise NotImplementedError
        yield  # pragma: no cover


def create_synthesizer() -> Synthesizer:
    settings = get_settings()
    if settings.tts_provider == "elevenlabs":
        return ElevenLabsSynthesizer(settings.elevenlabs_api_key)
    if settings.tts_provider == "cartesia":
        return CartesiaSynthesizer(settings.cartesia_api_key)
    raise ValueError(f"Unknown TTS_PROVIDER: {settings.tts_provider}")
