from __future__ import annotations

import asyncio
import json
from threading import Thread
from typing import Any

from anthropic import APIError, AsyncAnthropic
from pydantic import ValidationError

from src.config import settings
from src.parser.models import JDParsed

MODEL = "claude-sonnet-4-6"
MAX_INPUT_CHARS = 8_000

SYSTEM_PROMPT = """Jesteś parserem ogłoszeń o pracę. Wyciągasz ze wklejonego tekstu
DOKŁADNIE następujące dane jako JSON.

Schemat:
{
  "title": "string",
  "seniority": "junior|mid|senior|lead|expert|null",
  "tech_stack": ["string"],
  "location": "string|null",
  "work_mode": "remote|hybrid|onsite|null",
  "salary": {
    "min": 0,
    "max": 0,
    "currency": "PLN|EUR|USD",
    "period": "month|hour",
    "contract": "b2b|uop"
  } | null,
  "keywords": ["string"],
  "language": "pl|en",
  "raw_text": "oryginalny tekst"
}

Zasady:
- Jeśli czegoś nie ma w ogłoszeniu, zwróć null albo pustą listę.
- Nie halucynuj danych.
- Tech stack normalizuj: "py" -> "Python", "JS" -> "JavaScript", "k8s" -> "Kubernetes".
- Salary: jeśli widełki podane bez waluty, zakładaj PLN.
- Stawki godzinowe typu "120-150 PLN/h" ustaw jako period="hour" i zwykle contract="b2b".
- Wynagrodzenie miesięczne brutto bez jasnego kontraktu ustaw jako contract="uop".
- OUTPUT: tylko JSON, bez markdown code fences, bez komentarzy.
"""


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
                model=MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
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
    return text[:MAX_INPUT_CHARS]


def _build_user_prompt(text: str) -> str:
    return f"Przeparsuj poniższe ogłoszenie do JSON zgodnego ze schematem:\n\n{text}"


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
