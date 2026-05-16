"""Testy fundamentów scraperów — JobOffer, SalaryRange, BaseScraper."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from src.scrapers.base import (
    BaseScraper,
    JobOffer,
    SalaryRange,
    SearchParams,
    utcnow,
)


class TestSalaryRange:
    def test_valid_range_creates(self) -> None:
        sal = SalaryRange(min=10000, max=15000, currency="PLN", period="month", contract="b2b")
        assert sal.min == 10000
        assert sal.max == 15000

    def test_min_greater_than_max_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot exceed max"):
            SalaryRange(min=20000, max=15000, currency="PLN", period="month", contract="b2b")

    def test_negative_salary_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot be negative"):
            SalaryRange(min=-100, max=15000, currency="PLN", period="month", contract="b2b")

    def test_equal_min_max_allowed(self) -> None:
        # Stała stawka (np. dla juniora) — min == max powinno działać
        sal = SalaryRange(min=8000, max=8000, currency="PLN", period="month", contract="uop")
        assert sal.min == sal.max

    def test_is_frozen(self) -> None:
        sal = SalaryRange(min=10000, max=15000, currency="PLN", period="month", contract="b2b")
        with pytest.raises(FrozenInstanceError):
            sal.min = 20000  # type: ignore[misc]

    def test_is_hashable(self) -> None:
        sal1 = SalaryRange(min=10000, max=15000, currency="PLN", period="month", contract="b2b")
        sal2 = SalaryRange(min=10000, max=15000, currency="PLN", period="month", contract="b2b")
        assert hash(sal1) == hash(sal2)
        assert {sal1, sal2} == {sal1}


class TestJobOffer:
    def test_creates_with_all_fields(self, sample_job_offer: JobOffer) -> None:
        assert sample_job_offer.title == "Senior Python Developer"
        assert sample_job_offer.portal == "justjoin.it"
        assert "Python" in sample_job_offer.tech_stack

    def test_is_frozen(self, sample_job_offer: JobOffer) -> None:
        with pytest.raises(FrozenInstanceError):
            sample_job_offer.title = "Junior Dev"  # type: ignore[misc]

    def test_is_hashable(self, sample_job_offer: JobOffer) -> None:
        # Hashable wymagane do dedup (set-based)
        assert hash(sample_job_offer) is not None

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            JobOffer(
                title="Test",
                company="X",
                portal="test",
                url="https://x",
                location=None,
                work_mode=None,
                seniority=None,
                tech_stack=(),
                salary=None,
                published_at=datetime(2026, 1, 1),  # bez tz
                scraped_at=datetime.now(UTC),
            )

    def test_naive_scraped_at_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            JobOffer(
                title="Test",
                company="X",
                portal="test",
                url="https://x",
                location=None,
                work_mode=None,
                seniority=None,
                tech_stack=(),
                salary=None,
                published_at=datetime.now(UTC),
                scraped_at=datetime(2026, 1, 1),  # bez tz
            )


class TestSearchParams:
    def test_defaults_are_empty(self) -> None:
        params = SearchParams()
        assert params.keywords == ()
        assert params.location is None
        assert params.limit == 100

    def test_is_frozen(self) -> None:
        params = SearchParams(keywords=("python",), limit=50)
        with pytest.raises(FrozenInstanceError):
            params.limit = 200  # type: ignore[misc]


class TestBaseScraper:
    def test_cannot_instantiate_directly(self) -> None:
        # Abstract — instancjowanie bez implementacji abstract methods rzuca
        with pytest.raises(TypeError):
            BaseScraper()  # type: ignore[abstract]

    def test_subclass_must_implement_fetch_and_normalize(self) -> None:
        class IncompleteScraper(BaseScraper):
            portal_name = "incomplete"
            # brak fetch i normalize

        with pytest.raises(TypeError):
            IncompleteScraper()  # type: ignore[abstract]


class TestUtcNow:
    def test_returns_aware_datetime(self) -> None:
        now = utcnow()
        assert now.tzinfo is not None
        assert now.tzinfo == UTC
