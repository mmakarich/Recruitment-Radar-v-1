from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from src.scrapers import JobOffer, RocketJobsScraper, SalaryRange, SearchParams
from src.scrapers.base import ScraperHTTPError, ScraperTimeoutError
from src.scrapers.rocketjobs import API_URL


@pytest.fixture()
def rocketjobs_sample() -> dict[str, Any]:
    return json.loads(Path("tests/fixtures/rocketjobs_sample.json").read_text())


@pytest.fixture()
def rocketjobs_full_offer(rocketjobs_sample: dict[str, Any]) -> dict[str, Any]:
    return rocketjobs_sample["data"][0]


class TestNormalize:
    def test_normalize_full_offer(self, rocketjobs_full_offer: dict[str, Any]) -> None:
        offer = RocketJobsScraper().normalize(rocketjobs_full_offer)

        assert isinstance(offer, JobOffer)
        assert offer.title == "Marketing Automation Specialist"
        assert offer.company == "Growth Wizards"
        assert offer.portal == "rocketjobs.pl"
        assert offer.url.startswith("https://rocketjobs.pl/oferta-pracy/")
        assert offer.location == "Warszawa"
        assert offer.work_mode == "remote"
        assert offer.seniority == "mid"
        assert offer.tech_stack == ("Marketing Automation", "HubSpot", "SQL")
        assert offer.salary == SalaryRange(
            min=12000,
            max=17000,
            currency="PLN",
            period="month",
            contract="b2b",
        )
        assert offer.published_at.year == 2025
        assert offer.raw is rocketjobs_full_offer

    def test_normalize_missing_salary(self, rocketjobs_sample: dict[str, Any]) -> None:
        third = rocketjobs_sample["data"][2]
        offer = RocketJobsScraper().normalize(third)

        assert offer.salary is None
        assert offer.work_mode == "onsite"
        assert offer.seniority == "expert"

    def test_normalize_salary_only_unsupported_contract(
        self,
        rocketjobs_sample: dict[str, Any],
    ) -> None:
        second = rocketjobs_sample["data"][1]
        offer = RocketJobsScraper().normalize(second)

        assert offer.salary is None
        assert offer.work_mode == "hybrid"
        assert offer.seniority == "senior"

    def test_normalize_missing_location(self, rocketjobs_sample: dict[str, Any]) -> None:
        third = rocketjobs_sample["data"][2]
        offer = RocketJobsScraper().normalize(third)

        assert offer.location is None

    def test_normalize_joins_multiple_cities(self, rocketjobs_sample: dict[str, Any]) -> None:
        second = rocketjobs_sample["data"][1]
        offer = RocketJobsScraper().normalize(second)

        assert offer.location == "Kraków, Wrocław"

    def test_normalize_prefers_b2b_over_permanent(
        self,
        rocketjobs_full_offer: dict[str, Any],
    ) -> None:
        modified = copy.deepcopy(rocketjobs_full_offer)
        modified["employmentTypes"] = list(reversed(modified["employmentTypes"]))

        offer = RocketJobsScraper().normalize(modified)

        assert offer.salary is not None
        assert offer.salary.contract == "b2b"
        assert offer.salary.min == 12000

    def test_normalize_url_fallback_from_slug(
        self,
        rocketjobs_full_offer: dict[str, Any],
    ) -> None:
        modified = copy.deepcopy(rocketjobs_full_offer)
        modified.pop("link", None)

        offer = RocketJobsScraper().normalize(modified)

        assert offer.url == f"https://rocketjobs.pl/oferta-pracy/{modified['slug']}"

    def test_normalize_unknown_workplace_type_is_none(
        self,
        rocketjobs_full_offer: dict[str, Any],
    ) -> None:
        modified = copy.deepcopy(rocketjobs_full_offer)
        modified["workplaceType"] = "atlantis"

        offer = RocketJobsScraper().normalize(modified)

        assert offer.work_mode is None


class TestFetch:
    @respx.mock
    async def test_fetch_uses_mocked_api(self, rocketjobs_sample: dict[str, Any]) -> None:
        route = respx.get(host="api.rocketjobs.pl").mock(
            side_effect=[
                httpx.Response(200, json=rocketjobs_sample),
                httpx.Response(200, json={"data": [], "meta": {}}),
            ]
        )

        offers = await RocketJobsScraper().fetch(SearchParams(keywords=("marketing",), limit=10))

        assert route.called
        assert len(offers) == 3
        assert all(isinstance(offer, JobOffer) for offer in offers)
        assert all(offer.portal == "rocketjobs.pl" for offer in offers)

    @respx.mock
    async def test_fetch_respects_limit(self, rocketjobs_sample: dict[str, Any]) -> None:
        respx.get(host="api.rocketjobs.pl").mock(
            return_value=httpx.Response(200, json=rocketjobs_sample)
        )

        offers = await RocketJobsScraper().fetch(SearchParams(limit=2))

        assert len(offers) == 2

    @respx.mock
    async def test_fetch_retries_on_500(self, rocketjobs_sample: dict[str, Any]) -> None:
        respx.get(host="api.rocketjobs.pl").mock(
            side_effect=[
                httpx.Response(500),
                httpx.Response(500),
                httpx.Response(200, json=rocketjobs_sample),
                httpx.Response(200, json={"data": [], "meta": {}}),
            ]
        )

        offers = await RocketJobsScraper().fetch(SearchParams(limit=10))

        assert len(offers) == 3

    @respx.mock
    async def test_fetch_timeout_raises(self) -> None:
        respx.get(host="api.rocketjobs.pl").mock(side_effect=httpx.TimeoutException("slow"))

        with pytest.raises(ScraperTimeoutError):
            await RocketJobsScraper().fetch(SearchParams(limit=10))

    @respx.mock
    async def test_fetch_404_raises_http_error(self) -> None:
        respx.get(host="api.rocketjobs.pl").mock(return_value=httpx.Response(404))

        with pytest.raises(ScraperHTTPError):
            await RocketJobsScraper().fetch(SearchParams(limit=10))

    @respx.mock
    async def test_fetch_builds_query_with_seniority_and_keywords(
        self,
        rocketjobs_sample: dict[str, Any],
    ) -> None:
        route = respx.get(host="api.rocketjobs.pl").mock(
            return_value=httpx.Response(200, json=rocketjobs_sample)
        )

        await RocketJobsScraper().fetch(
            SearchParams(keywords=("marketing", "automation"), seniority="senior", limit=5)
        )

        called_url = str(route.calls[0].request.url)
        assert "keyword=marketing+automation" in called_url or (
            "keyword=marketing%20automation" in called_url
        )
        assert "experience-level=senior" in called_url

    @respx.mock
    async def test_fetch_sends_realistic_user_agent(
        self,
        rocketjobs_sample: dict[str, Any],
    ) -> None:
        route = respx.get(host="api.rocketjobs.pl").mock(
            return_value=httpx.Response(200, json=rocketjobs_sample)
        )

        await RocketJobsScraper().fetch(SearchParams(limit=5))

        ua = route.calls[0].request.headers.get("user-agent", "")
        assert "Mozilla" in ua and "Chrome" in ua

    @respx.mock
    async def test_fetch_handles_bare_list_response(
        self,
        rocketjobs_sample: dict[str, Any],
    ) -> None:
        respx.get(url=API_URL, params={"orderBy": "DESC", "sortBy": "newest", "page": "1"}).mock(
            return_value=httpx.Response(200, json=rocketjobs_sample["data"])
        )

        offers = await RocketJobsScraper().fetch(SearchParams(limit=10))

        assert len(offers) == 3
