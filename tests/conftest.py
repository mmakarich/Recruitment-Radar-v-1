"""Globalne fixtures dla pytest. Importowane automatycznie przez wszystkie testy."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import respx

from src.matching.compare import JDParsed, MatchScore
from src.matching.dedup import DedupedOffer
from src.matching.pipeline import MatchedOffer
from src.scrapers.base import JobOffer, SalaryRange


@pytest.fixture()
def sample_salary() -> SalaryRange:
    return SalaryRange(
        min=10000,
        max=15000,
        currency="PLN",
        period="month",
        contract="b2b",
    )


@pytest.fixture()
def sample_job_offer(sample_salary: SalaryRange) -> JobOffer:
    return JobOffer(
        title="Senior Python Developer",
        company="Example Company",
        portal="justjoin.it",
        url="https://example.com/job/python-developer",
        location="Warszawa",
        work_mode="remote",
        seniority="mid",
        tech_stack=("Python", "FastAPI"),
        salary=sample_salary,
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        scraped_at=datetime(2026, 1, 2, tzinfo=UTC),
        raw={"id": "sample"},
    )


@pytest.fixture()
def mock_httpx() -> Any:
    with respx.mock as respx_mock:
        yield respx_mock


@pytest.fixture()
def justjoin_sample() -> dict[str, Any]:
    return json.loads(Path("tests/fixtures/justjoin_sample.json").read_text())


@pytest.fixture()
def justjoin_full_offer(justjoin_sample: dict[str, Any]) -> dict[str, Any]:
    return justjoin_sample["data"][0]


# ---------------------------------------------------------------------------
# Helpery dla testow export (Prompt 8)
# ---------------------------------------------------------------------------


def make_matched_offer(job_offer: JobOffer, score: int = 75) -> MatchedOffer:
    """Tworzy MatchedOffer z minimalnym DedupedOffer i MatchScore do testow."""
    deduped = DedupedOffer(
        primary=job_offer,
        duplicates=(),
        portals=(job_offer.portal,),
        salary_variants=(job_offer.salary,) if job_offer.salary else (),
        match_confidence=100,
    )
    ms = MatchScore(
        total=score,
        title_score=score,
        company_score=0,
        tech_overlap=0.5,
        seniority_match=True,
        location_match=True,
        work_mode_match=True,
        salary_delta=None,
    )
    return MatchedOffer(deduped=deduped, match_score=ms)


@pytest.fixture
def sample_jd() -> JDParsed:
    """Przykladowe sparsowane ogloszenie do testow exportu."""
    from src.scrapers.base import SalaryRange

    return JDParsed(
        title="Senior Python Developer",
        company="Acme Corp",
        location="Warsaw",
        work_mode="hybrid",
        seniority="senior",
        tech_stack=("Python", "FastAPI", "AWS"),
        salary=SalaryRange(min=18000, max=25000, currency="PLN", period="month", contract="b2b"),
    )
