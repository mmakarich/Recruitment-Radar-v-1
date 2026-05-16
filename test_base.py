"""Testy bazowej infrastruktury scrapera."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.scrapers.base import (
    BaseScraper,
    JobOffer,
    SalaryRange,
    SearchParams,
)


def _make_offer(**overrides: object) -> JobOffer:
    defaults: dict[str, object] = {
        "title": "Python Dev",
        "company": "Acme",
        "portal": "justjoin.it",
        "url": "https://justjoin.it/job-offer/x",
        "location": "Warszawa",
        "work_mode": "remote",
        "seniority": "mid",
        "tech_stack": ("Python",),
        "salary": None,
        "published_at": datetime.now(UTC),
        "scraped_at": datetime.now(UTC),
        "raw": {},
    }
    defaults.update(overrides)
    return JobOffer(**defaults)  # type: ignore[arg-type]


def test_job_offer_is_frozen() -> None:
    offer = _make_offer()
    with pytest.raises((AttributeError, TypeError)):
        offer.title = "other"  # type: ignore[misc]


def test_job_offer_is_hashable_despite_dict_raw() -> None:
    offer = _make_offer(raw={"big": "payload"})
    # raw jest wykluczone z hash/compare, wiec JobOffer jest hashable.
    assert isinstance(hash(offer), int)


def test_salary_range_rejects_min_greater_than_max() -> None:
    with pytest.raises(ValueError):
        SalaryRange(min=10_000, max=5_000, currency="PLN", period="month", contract="b2b")


def test_salary_range_rejects_negative_values() -> None:
    with pytest.raises(ValueError):
        SalaryRange(min=-1, max=100, currency="PLN", period="month", contract="b2b")


def test_base_scraper_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        BaseScraper()  # type: ignore[abstract]


def test_search_params_defaults() -> None:
    params = SearchParams()
    assert params.keywords == ()
    assert params.limit == 100
    assert params.location is None
