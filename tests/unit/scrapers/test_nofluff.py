from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from src.scrapers import JobOffer, NoFluffScraper, SalaryRange, SearchParams
from src.scrapers.base import ScraperHTTPError, ScraperTimeoutError
from src.scrapers.nofluff import API_URL


@pytest.fixture()
def nofluff_sample() -> dict[str, Any]:
    return json.loads(Path("tests/fixtures/nofluff_sample.json").read_text())


@pytest.fixture()
def nofluff_full_offer(nofluff_sample: dict[str, Any]) -> dict[str, Any]:
    return nofluff_sample["data"][0]


class TestNormalize:
    def test_normalize_full_offer(self, nofluff_full_offer: dict[str, Any]) -> None:
        offer = NoFluffScraper().normalize(nofluff_full_offer)

        assert isinstance(offer, JobOffer)
        assert offer.title == "Senior Python Developer"
        assert offer.company == "Data Wizards"
        assert offer.portal == "nofluffjobs.com"
        assert offer.url == "https://nofluffjobs.com/job/senior-python-developer-data-wizards"
        assert offer.location == "Warszawa, Kraków"
        assert offer.work_mode == "remote"
        assert offer.seniority == "senior"
        assert offer.tech_stack == ("Python", "Django", "AWS")
        assert offer.salary == SalaryRange(
            min=22000,
            max=28000,
            currency="PLN",
            period="month",
            contract="b2b",
        )
        assert offer.published_at.year == 2025
        assert offer.raw is nofluff_full_offer

    def test_normalize_undisclosed_salary(self, nofluff_sample: dict[str, Any]) -> None:
        offer = NoFluffScraper().normalize(nofluff_sample["data"][1])

        assert offer.salary is None
        assert offer.company == "Backend House"
        assert offer.work_mode == "hybrid"
        assert offer.seniority == "mid"

    def test_normalize_multiple_locations(self, nofluff_sample: dict[str, Any]) -> None:
        offer = NoFluffScraper().normalize(nofluff_sample["data"][2])

        assert offer.location == "Wrocław, Poznań"

    def test_normalize_salary_from_ranges(self, nofluff_sample: dict[str, Any]) -> None:
        offer = NoFluffScraper().normalize(nofluff_sample["data"][2])

        assert offer.salary == SalaryRange(
            min=25000,
            max=32000,
            currency="PLN",
            period="month",
            contract="uop",
        )

    def test_normalize_missing_location(self, nofluff_full_offer: dict[str, Any]) -> None:
        modified = dict(nofluff_full_offer)
        modified["location"] = {"places": []}

        offer = NoFluffScraper().normalize(modified)

        assert offer.location is None


class TestFetch:
    @respx.mock
    async def test_fetch_uses_mocked_api(self, nofluff_sample: dict[str, Any]) -> None:
        route = respx.get(host="nofluffjobs.com").mock(
            side_effect=[
                httpx.Response(200, json=nofluff_sample),
                httpx.Response(200, json={"data": []}),
            ]
        )

        offers = await NoFluffScraper().fetch(SearchParams(keywords=("python",), limit=10))

        assert route.called
        assert len(offers) == 3
        assert all(isinstance(offer, JobOffer) for offer in offers)
        assert all(offer.portal == "nofluffjobs.com" for offer in offers)

    @respx.mock
    async def test_fetch_respects_limit(self, nofluff_sample: dict[str, Any]) -> None:
        respx.get(host="nofluffjobs.com").mock(
            return_value=httpx.Response(200, json=nofluff_sample)
        )

        offers = await NoFluffScraper().fetch(SearchParams(limit=2))

        assert len(offers) == 2

    @respx.mock
    async def test_fetch_retries_on_500(self, nofluff_sample: dict[str, Any]) -> None:
        respx.get(host="nofluffjobs.com").mock(
            side_effect=[
                httpx.Response(500),
                httpx.Response(500),
                httpx.Response(200, json=nofluff_sample),
                httpx.Response(200, json={"data": []}),
            ]
        )

        offers = await NoFluffScraper().fetch(SearchParams(limit=10))

        assert len(offers) == 3

    @respx.mock
    async def test_fetch_timeout_raises(self) -> None:
        respx.get(host="nofluffjobs.com").mock(side_effect=httpx.TimeoutException("slow"))

        with pytest.raises(ScraperTimeoutError):
            await NoFluffScraper().fetch(SearchParams(limit=10))

    @respx.mock
    async def test_fetch_404_raises_http_error(self) -> None:
        respx.get(host="nofluffjobs.com").mock(return_value=httpx.Response(404))

        with pytest.raises(ScraperHTTPError):
            await NoFluffScraper().fetch(SearchParams(limit=10))

    @respx.mock
    async def test_fetch_builds_query_with_seniority_and_keywords(
        self,
        nofluff_sample: dict[str, Any],
    ) -> None:
        route = respx.get(host="nofluffjobs.com").mock(
            return_value=httpx.Response(200, json=nofluff_sample)
        )

        await NoFluffScraper().fetch(
            SearchParams(keywords=("python", "fastapi"), seniority="senior", limit=5)
        )

        called_url = str(route.calls[0].request.url)
        assert "criteria=python+fastapi" in called_url or "criteria=python%20fastapi" in called_url
        assert "seniority=senior" in called_url

    @respx.mock
    async def test_fetch_handles_bare_list_response(self, nofluff_sample: dict[str, Any]) -> None:
        respx.get(url=API_URL, params={"sort": "newest", "page": "1"}).mock(
            return_value=httpx.Response(200, json=nofluff_sample["data"])
        )

        offers = await NoFluffScraper().fetch(SearchParams(limit=10))

        assert len(offers) == 3
