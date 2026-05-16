from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from src.scrapers import JobOffer, SalaryRange, SearchParams, TheProtocolScraper
from src.scrapers.base import ScraperHTTPError, ScraperStructureChangedError, ScraperTimeoutError
from src.scrapers.theprotocol import (
    extract_next_data_from_html,
    extract_offers_from_next_data,
)


@pytest.fixture()
def theprotocol_next_data() -> dict[str, Any]:
    return json.loads(Path("tests/fixtures/theprotocol_sample.json").read_text())


@pytest.fixture()
def theprotocol_html() -> str:
    return Path("tests/fixtures/theprotocol_sample.html").read_text()


@pytest.fixture()
def theprotocol_offer(theprotocol_next_data: dict[str, Any]) -> dict[str, Any]:
    offers = extract_offers_from_next_data(theprotocol_next_data)
    return offers[0]


class TestExtractNextData:
    def test_extract_next_data_from_html(self, theprotocol_html: str) -> None:
        next_data = extract_next_data_from_html(theprotocol_html)

        offers = extract_offers_from_next_data(next_data)

        assert len(offers) == 3
        assert offers[0]["title"] == "Senior Python Developer"

    def test_structure_changed_raises(self) -> None:
        with pytest.raises(ScraperStructureChangedError):
            extract_next_data_from_html("<html><body>No next data</body></html>")


class TestNormalize:
    def test_normalize_full_offer(self, theprotocol_offer: dict[str, Any]) -> None:
        offer = TheProtocolScraper().normalize(theprotocol_offer)

        assert isinstance(offer, JobOffer)
        assert offer.title == "Senior Python Developer"
        assert offer.company == "Protocol Software"
        assert offer.portal == "theprotocol.it"
        assert offer.url.startswith("https://theprotocol.it/szczegoly/praca/")
        assert offer.location == "Warszawa, Mazovian"
        assert offer.work_mode == "remote"
        assert offer.seniority == "senior"
        assert offer.tech_stack == ("Python", "FastAPI", "AWS")
        assert offer.salary == SalaryRange(
            min=22000,
            max=28000,
            currency="PLN",
            period="month",
            contract="b2b",
        )
        assert offer.published_at.year == 2026
        assert offer.raw is theprotocol_offer

    def test_normalize_eur_salary(self, theprotocol_next_data: dict[str, Any]) -> None:
        raw = extract_offers_from_next_data(theprotocol_next_data)[1]

        offer = TheProtocolScraper().normalize(raw)

        assert offer.salary == SalaryRange(
            min=5000,
            max=6500,
            currency="EUR",
            period="month",
            contract="uop",
        )
        assert offer.work_mode == "hybrid"
        assert offer.seniority == "mid"

    def test_normalize_missing_workplaces(self, theprotocol_next_data: dict[str, Any]) -> None:
        raw = extract_offers_from_next_data(theprotocol_next_data)[2]

        offer = TheProtocolScraper().normalize(raw)

        assert offer.location is None
        assert offer.salary is None
        assert offer.work_mode == "onsite"
        assert offer.seniority == "lead"


class TestFetch:
    @respx.mock
    async def test_fetch_paginates(self, theprotocol_html: str) -> None:
        empty_next_data = {"props": {"pageProps": {"jobOffers": {"items": []}}}}
        empty_html = (
            '<html><body><script id="__NEXT_DATA__" type="application/json">'
            f"{json.dumps(empty_next_data)}"
            "</script></body></html>"
        )
        route = respx.get(host="theprotocol.it").mock(
            side_effect=[
                httpx.Response(200, text=theprotocol_html),
                httpx.Response(200, text=empty_html),
            ]
        )

        offers = await TheProtocolScraper().fetch(SearchParams(keywords=("python",), limit=10))

        assert route.called
        assert len(offers) == 3
        assert all(offer.portal == "theprotocol.it" for offer in offers)

    @respx.mock
    async def test_fetch_respects_limit(self, theprotocol_html: str) -> None:
        respx.get(host="theprotocol.it").mock(
            return_value=httpx.Response(200, text=theprotocol_html)
        )

        offers = await TheProtocolScraper().fetch(SearchParams(keywords=("python",), limit=2))

        assert len(offers) == 2

    @respx.mock
    async def test_fetch_timeout_raises(self) -> None:
        respx.get(host="theprotocol.it").mock(side_effect=httpx.TimeoutException("slow"))

        with pytest.raises(ScraperTimeoutError):
            await TheProtocolScraper().fetch(SearchParams(keywords=("python",), limit=10))

    @respx.mock
    async def test_fetch_404_raises_http_error(self) -> None:
        respx.get(host="theprotocol.it").mock(return_value=httpx.Response(404))

        with pytest.raises(ScraperHTTPError):
            await TheProtocolScraper().fetch(SearchParams(keywords=("python",), limit=10))
