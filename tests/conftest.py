"""Globalne fixtures dla pytest. Importowane automatycznie przez wszystkie testy."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import respx

from src.scrapers.base import JobOffer, SalaryRange


@pytest.fixture
def sample_salary() -> SalaryRange:
    """Przykładowy SalaryRange dla testów."""
    return SalaryRange(
        min=15000,
        max=22000,
        currency="PLN",
        period="month",
        contract="b2b",
    )


@pytest.fixture
def sample_job_offer(sample_salary: SalaryRange) -> JobOffer:
    """Przykładowa oferta pracy — używana w testach modułów konsumujących JobOffer."""
    return JobOffer(
        title="Senior Python Developer",
        company="Acme Corp",
        portal="justjoin.it",
        url="https://justjoin.it/job-offer/acme-senior-python",
        location="Warsaw",
        work_mode="hybrid",
        seniority="senior",
        tech_stack=("Python", "FastAPI", "PostgreSQL", "AWS"),
        salary=sample_salary,
        published_at=datetime(2026, 5, 10, 9, 0, 0, tzinfo=UTC),
        scraped_at=datetime(2026, 5, 16, 6, 0, 0, tzinfo=UTC),
        raw={"id": "test-123", "slug": "acme-senior-python"},
    )


@pytest.fixture
def mock_httpx() -> respx.MockRouter:
    """respx mock router — używaj jako kontekstu w testach scraperów.

    Przykład:
        def test_xxx(mock_httpx):
            mock_httpx.get("https://api.example.com").respond(200, json={...})
            ...
    """
    with respx.mock(assert_all_called=False) as router:
        yield router
