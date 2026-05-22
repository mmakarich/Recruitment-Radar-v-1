from __future__ import annotations

import asyncio
import json
from functools import lru_cache
from pathlib import Path
from threading import Thread
from typing import Any

from anthropic import APIError, AsyncAnthropic
from pydantic import ValidationError

from src.config import settings
from src.parser.models import JDParsed

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "jd_parser.md"


class JDParserError(Exception):
    """Błąd parsowania Job Description."""


async def parse_jd(text: str, client: AsyncAnthropic | Any | None = None) -> JDParsed:
    source_text = _truncate_text(text)
    if not source_text.strip():
        raise JDParserError("JD text cannot be empty")

    if client is None and not settings.ANTHROPIC_API_KEY:
        raise JDParserError(
            "ANTHROPIC_API_KEY is not configured. "
            "Add it in Streamlit Cloud secrets to enable JD parsing."
        )

    anthropic_client = client or AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    user_prompt = _build_user_prompt(source_text)

    last_error: Exception | None = None

    for attempt in range(2):
        try:
            response = await anthropic_client.messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=1024,
                system=_system_prompt(),
                messages=[{"role": "user", "content": user_prompt}],
            )
            payload = json.loads(_response_text(response))
            return JDParsed.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            if attempt == 0:
                user_prompt = _build_retry_prompt(source_text, str(exc))
                continue
            raise JDParserError(f"Claude response did not match JD schema: {exc}") from exc
        except APIError as exc:
            raise JDParserError(f"Anthropic API error: {exc}") from exc

    raise JDParserError(f"JD parsing failed: {last_error}")


def parse_jd_sync(text: str) -> JDParsed:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(parse_jd(text))

    value_box: list[JDParsed] = []
    error_box: list[BaseException] = []

    def _runner() -> None:
        try:
            value_box.append(asyncio.run(parse_jd(text)))
        except BaseException as exc:
            error_box.append(exc)

    thread = Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if error_box:
        raise error_box[0]

    if not value_box:
        raise JDParserError("JD parser thread did not return a result")

    return value_box[0]


def _truncate_text(text: str) -> str:
    return text[: settings.JD_PARSER_MAX_INPUT_CHARS]


@lru_cache(maxsize=1)
def _system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise JDParserError(f"JD parser prompt file is missing: {PROMPT_PATH}") from exc


def _build_user_prompt(text: str) -> str:
    return (
        "Przeparsuj poniższe ogłoszenie do JSON zgodnego ze schematem. "
        "Dla długich JD umieść w tech_stack tylko kluczowe wymagania, a technologie "
        "opcjonalne lub poboczne przenieś do keywords.\n\n"
        f"{text}"
    )


def _build_retry_prompt(text: str, error: str) -> str:
    return (
        "Poprzednia odpowiedź była niepoprawnym JSON albo nie spełniła schematu. "
        f"Błąd walidacji: {error}\n\n"
        "Zwróć ponownie wyłącznie poprawny JSON dla tego ogłoszenia:\n\n"
        f"{text}"
    )


def _response_text(response: Any) -> str:
    if isinstance(response, str):
        return response

    if isinstance(response, dict):
        content = response.get("content")
    else:
        content = getattr(response, "content", None)

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)

        return "\n".join(parts)

    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text

    return ""
