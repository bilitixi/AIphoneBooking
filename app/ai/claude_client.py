from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

from app.core.config import get_settings

_client: AsyncAnthropic | None = None


def get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def stream_reply(
    system: str,
    messages: list[dict],
    tools: list[dict],
) -> AsyncIterator[dict]:
    """Streams raw Anthropic message-stream events. reservation_agent.py owns
    interpreting them (text deltas vs tool_use blocks vs stop reasons)."""
    settings = get_settings()
    client = get_client()

    async with client.messages.stream(
        model=settings.claude_model,
        max_tokens=1024,
        system=system,
        messages=messages,
        tools=tools,
    ) as stream:
        async for event in stream:
            yield event
