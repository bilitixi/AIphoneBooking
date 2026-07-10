"""Streaming TTS client wrapper.

ElevenLabs is wired up as the default (§7.1 called for prototyping 2 vendors
— ElevenLabs is implemented for real below; Cartesia is still a stub). Same
rationale as transcriber.py: isolate the vendor behind this interface.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Shared across requests so each reply doesn't pay a fresh TLS handshake.
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=30.0)
    return _http_client


class Synthesizer(ABC):
    @abstractmethod
    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """Yields audio chunks (mu-law/8kHz, matching Twilio's expected format)
        for the given agent reply text."""


class ElevenLabsSynthesizer(Synthesizer):
    """Requests mulaw/8kHz output directly (`output_format=ulaw_8000`) so the
    bytes can be forwarded to Twilio's media stream with no transcoding."""

    def __init__(self, api_key: str, voice_id: str):
        self._api_key = api_key
        self._voice_id = voice_id

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}/stream"
        params = {"output_format": "ulaw_8000"}
        headers = {"xi-api-key": self._api_key, "Content-Type": "application/json"}
        payload = {
            "text": text,
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }

        client = _get_http_client()
        try:
            async with client.stream(
                "POST", url, params=params, headers=headers, json=payload
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk
        except httpx.HTTPError:
            logger.exception("ElevenLabs TTS request failed")


class CartesiaSynthesizer(Synthesizer):
    def __init__(self, api_key: str):
        self._api_key = api_key

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        raise NotImplementedError
        yield  # pragma: no cover


def create_synthesizer() -> Synthesizer:
    settings = get_settings()
    if settings.tts_provider == "elevenlabs":
        return ElevenLabsSynthesizer(settings.elevenlabs_api_key, settings.elevenlabs_voice_id)
    if settings.tts_provider == "cartesia":
        return CartesiaSynthesizer(settings.cartesia_api_key)
    raise ValueError(f"Unknown TTS_PROVIDER: {settings.tts_provider}")
