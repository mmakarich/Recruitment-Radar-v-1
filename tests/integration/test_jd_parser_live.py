from __future__ import annotations

import pytest

from src.config import settings
from src.parser.jd_parser import parse_jd


@pytest.mark.live
async def test_jd_parser_live_with_claude_api() -> None:
    if not settings.ANTHROPIC_API_KEY:
        pytest.skip("ANTHROPIC_API_KEY not configured")

    sample = """
    Szukamy Senior Python Developera do zespołu backendowego.
    Wymagamy Python, FastAPI, PostgreSQL i Docker.
    Praca zdalna, B2B, 120-150 PLN/h.
    """

    parsed = await parse_jd(sample)

    assert parsed.title
    assert "Python" in parsed.tech_stack
    assert parsed.language == "pl"
