from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from src.parser.jd_parser import JDParserError, parse_jd, parse_jd_sync
from src.parser.models import JDParsed, SalaryRange


@dataclass(slots=True)
class _TextBlock:
    text: str


@dataclass(slots=True)
class _Response:
    content: list[_TextBlock]


class _MockMessages:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _Response:
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("No mocked Anthropic responses left")
        return _Response(content=[_TextBlock(text=self._responses.pop(0))])


class _MockClient:
    def __init__(self, responses: list[str]) -> None:
        self.messages = _MockMessages(responses)


def _payload(
    *,
    title: str = "Senior Python Developer",
    seniority: str | None = "senior",
    tech_stack: list[str] | None = None,
    location: str | None = "Warszawa",
    work_mode: str | None = "remote",
    salary: dict[str, Any] | None = None,
    keywords: list[str] | None = None,
    language: str = "pl",
    raw_text: str = "Sample JD",
) -> str:
    return json.dumps(
        {
            "title": title,
            "seniority": seniority,
            "tech_stack": tech_stack if tech_stack is not None else ["Python", "FastAPI", "AWS"],
            "location": location,
            "work_mode": work_mode,
            "salary": salary,
            "keywords": keywords if keywords is not None else ["fintech", "backend"],
            "language": language,
            "raw_text": raw_text,
        }
    )


@pytest.mark.asyncio
async def test_parse_polish_jd_with_salary() -> None:
    sample = Path("tests/fixtures/jd_samples/python_senior_pl.txt").read_text(encoding="utf-8")
    client = _MockClient(
        [
            _payload(
                salary={
                    "min": 120,
                    "max": 150,
                    "currency": "PLN",
                    "period": "hour",
                    "contract": "b2b",
                },
                raw_text=sample,
            )
        ]
    )

    parsed = await parse_jd(sample, client=client)

    assert isinstance(parsed, JDParsed)
    assert parsed.title == "Senior Python Developer"
    assert parsed.seniority == "senior"
    assert parsed.tech_stack == ("Python", "FastAPI", "AWS")
    assert parsed.location == "Warszawa"
    assert parsed.work_mode == "remote"
    assert parsed.salary == SalaryRange(
        min=120,
        max=150,
        currency="PLN",
        period="hour",
        contract="b2b",
    )
    assert parsed.language == "pl"
    assert client.messages.calls[0]["model"] == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_parse_english_jd_remote() -> None:
    sample = Path("tests/fixtures/jd_samples/react_mid_en.txt").read_text(encoding="utf-8")
    client = _MockClient(
        [
            _payload(
                title="Mid React Developer",
                seniority="mid",
                tech_stack=["React", "TypeScript", "JavaScript"],
                location=None,
                work_mode="remote",
                salary={
                    "min": 18000,
                    "max": 22000,
                    "currency": "PLN",
                    "period": "month",
                    "contract": "uop",
                },
                language="en",
                raw_text=sample,
            )
        ]
    )

    parsed = await parse_jd(sample, client=client)

    assert parsed.title == "Mid React Developer"
    assert parsed.seniority == "mid"
    assert parsed.work_mode == "remote"
    assert parsed.location is None
    assert parsed.language == "en"
    assert "React" in parsed.tech_stack


@pytest.mark.asyncio
async def test_parse_b2b_hourly_rate() -> None:
    client = _MockClient(
        [
            _payload(
                salary={
                    "min": 120,
                    "max": 150,
                    "currency": "PLN",
                    "period": "hour",
                    "contract": "b2b",
                }
            )
        ]
    )

    parsed = await parse_jd("Python developer 120-150 PLN/h B2B", client=client)

    assert parsed.salary is not None
    assert parsed.salary.period == "hour"
    assert parsed.salary.contract == "b2b"


@pytest.mark.asyncio
async def test_parse_missing_optional_fields() -> None:
    client = _MockClient(
        [
            _payload(
                title="Backend Developer",
                seniority=None,
                tech_stack=[],
                location=None,
                work_mode=None,
                salary=None,
                keywords=[],
            )
        ]
    )

    parsed = await parse_jd("Backend Developer", client=client)

    assert parsed.seniority is None
    assert parsed.tech_stack == ()
    assert parsed.location is None
    assert parsed.work_mode is None
    assert parsed.salary is None
    assert parsed.keywords == ("Backend Developer",)


@pytest.mark.asyncio
async def test_retry_on_invalid_json() -> None:
    client = _MockClient(
        [
            "not json",
            _payload(
                title="Lead DevOps Engineer",
                seniority="lead",
                tech_stack=["Kubernetes", "Docker", "AWS"],
            ),
        ]
    )

    parsed = await parse_jd("Lead DevOps Engineer", client=client)

    assert parsed.title == "Lead DevOps Engineer"
    assert parsed.seniority == "lead"
    assert len(client.messages.calls) == 2


@pytest.mark.asyncio
async def test_normalizes_tech_stack() -> None:
    client = _MockClient(
        [
            _payload(
                tech_stack=["py", "JS", "k8s", "Python", "nodejs"],
            )
        ]
    )

    parsed = await parse_jd("Python JS k8s", client=client)

    assert parsed.tech_stack == ("Python", "JavaScript", "Kubernetes", "Node.js")


@pytest.mark.asyncio
async def test_filters_keywords_to_job_search_terms() -> None:
    client = _MockClient(
        [
            _payload(
                title="Senior Java Developer",
                tech_stack=["Java", "Spring Boot"],
                keywords=[
                    "Java 17",
                    "Java 21",
                    "Spring Boot 3.3.x",
                    "taxation",
                    "pension",
                    "savings",
                    "investment",
                    "PostgreSQL",
                    "JMS",
                    "MQ",
                    "OpenAPI",
                    "AsyncAPI",
                    "CI/CD",
                    "upgrade",
                    "calculation engine",
                    "financial",
                ],
            )
        ]
    )

    parsed = await parse_jd("Senior Java Developer", client=client)

    assert parsed.keywords == (
        "Senior Java Developer",
        "Java",
        "Spring Boot",
        "PostgreSQL",
    )


@pytest.mark.asyncio
async def test_invalid_after_retry_raises() -> None:
    client = _MockClient(["not json", "also not json"])

    with pytest.raises(JDParserError):
        await parse_jd("Broken JD", client=client)


@pytest.mark.asyncio
async def test_empty_text_raises() -> None:
    with pytest.raises(JDParserError):
        await parse_jd("   ", client=_MockClient([]))


def test_missing_anthropic_api_key_raises_parser_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.parser.jd_parser.settings.ANTHROPIC_API_KEY", "")

    with pytest.raises(JDParserError, match="ANTHROPIC_API_KEY is not configured"):
        parse_jd_sync("Senior Python Developer")


@pytest.mark.asyncio
async def test_uses_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.parser.jd_parser.settings.ANTHROPIC_MODEL", "claude-test-model")
    client = _MockClient([_payload()])

    await parse_jd("Senior Python Developer", client=client)

    assert client.messages.calls[0]["model"] == "claude-test-model"


@pytest.mark.asyncio
async def test_uses_prompt_file_with_long_jd_guidance() -> None:
    client = _MockClient([_payload()])

    await parse_jd("Senior Node.js Developer", client=client)

    system_prompt = client.messages.calls[0]["system"]
    user_prompt = client.messages.calls[0]["messages"][0]["content"]
    assert "must-have" in system_prompt
    assert "nice-to-have" in system_prompt
    assert "Dla długich JD" in user_prompt


@pytest.mark.asyncio
async def test_truncates_input_with_configured_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.parser.jd_parser.settings.JD_PARSER_MAX_INPUT_CHARS", 5)
    client = _MockClient([_payload()])

    await parse_jd("1234567890", client=client)

    assert client.messages.calls[0]["messages"][0]["content"].endswith("12345")
