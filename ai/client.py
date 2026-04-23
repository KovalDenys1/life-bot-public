"""
AI client: Claude (primary) with GPT-4o fallback and Haiku for quick questions.
"""
import logging
import user_profile as p
from config import anthropic_client, openai_client
from services.cost_tracker import track_claude, track_openai

logger = logging.getLogger(__name__)


def call_ai(
    system: str,
    user: str,
    max_tokens: int = 1000,
    history: list[dict] | None = None,
    prefill: str | None = None,
) -> str:
    """
    Call Claude Sonnet, fall back to GPT-4o on error.
    prefill: optional assistant-turn prefix to force output format (e.g. '{' for JSON).
    """
    messages = list(history or []) + [{"role": "user", "content": user}]
    if prefill:
        messages.append({"role": "assistant", "content": prefill})

    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        track_claude(response.usage.input_tokens, response.usage.output_tokens)
        raw = response.content[0].text.strip()
        return (prefill + raw) if prefill else raw

    except Exception as e:
        logger.warning(f"Claude failed ({e}), trying OpenAI fallback…")
        if not openai_client:
            raise
        openai_messages = [{"role": "system", "content": system}] + [
            m for m in messages if not (m["role"] == "assistant" and m.get("content") == prefill)
        ]
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            max_tokens=max_tokens,
            messages=openai_messages,
        )
        track_openai(response.usage.prompt_tokens, response.usage.completion_tokens)
        return response.choices[0].message.content.strip()


def process_quick_question(text: str) -> str:
    """Answer a simple question using Haiku — no vault, no JSON, cheap."""
    try:
        response = anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=f"You are a helpful assistant for {p.NAME}. Respond in English. Use Telegram HTML: <b>bold</b>, <code>code</code>. Be concise.",
            messages=[{"role": "user", "content": text}],
        )
        track_claude(response.usage.input_tokens, response.usage.output_tokens)
        return response.content[0].text.strip()
    except Exception as e:
        logger.error(f"Haiku error: {e}", exc_info=True)
        return "⚠️ Something went wrong. Please try again."
