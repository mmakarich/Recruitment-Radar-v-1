"""Testy jednostkowe scrapera justjoin.it.

Wszystko bez sieci — `fetch` mockujemy przez respx, `normalize` testujemy
czysto na dict.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import httpx
import pytest
import respx

from src.scrapers import JobOffer, JustJoinScraper, SalaryRange, SearchParams
from src.scrapers.base import ScraperHTTPError, ScraperTimeoutError
from src.scrapers.justjoin import API_URL, _extract_offers_from_frontend_html


class TestNormalize:
    def test_normalize_full_offer(self, justjoin_full_offer: dict[str, Any]) -> None:
        offer = JustJoinScraper().normalize(justjoin_full_offer)

        assert isinstance(offer, JobOffer)
        assert offer.title == "Junior+/Mid Frontend Developer"
        assert offer.company == "Innovation Software"
        assert offer.portal == "justjoin.it"
        assert offer.url.startswith("https://justjoin.it/job-offer/")
        assert offer.location == "Wrocław"
        assert offer.work_mode == "remote"
        assert offer.seniority == "mid"
        assert offer.tech_stack == ("React", "React Native", "PHP")
        assert offer.salary == SalaryRange(
            min=8000, max=13000, currency="PLN", period="month", contract="b2b"
        )
        assert offer.published_at.year == 2025
        assert offer.published_at.month == 2
        assert offer.raw is justjoin_full_offer

    def test_normalize_missing_salary(self, justjoin_sample: dict[str, Any]) -> None:
        # 3-cia oferta w fixture ma employmentTypes=[].
        third = justjoin_sample["data"][2]
        offer = JustJoinScraper().normalize(third)

        assert offer.salary is None
        assert offer.title == "Lead Architect"
        assert offer.work_mode == "onsite"
        assert offer.seniority == "expert"

    def test_normalize_salary_only_unsupported_contract(
        self, justjoin_sample: dict[str, Any]
    ) -> None:
        # 2-ga oferta ma tylko mandate_contract — nie mapuje sie na b2b/uop.
        second = justjoin_sample["data"][1]
        offer = JustJoinScraper().normalize(second)

        assert offer.salary is None
        assert offer.work_mode == "hybrid"
        assert offer.seniority == "senior"

    def test_normalize_missing_location(self, justjoin_sample: dict[str, Any]) -> None:
        # 3-cia oferta ma multilocation=[] i brak city top-level.
        third = justjoin_sample["data"][2]
        offer = JustJoinScraper().normalize(third)

        assert offer.location is None

    def test_normalize_joins_multiple_cities(self, justjoin_sample: dict[str, Any]) -> None:
        second = justjoin_sample["data"][1]
        offer = JustJoinScraper().normalize(second)

        assert offer.location == "Warszawa, Kraków"

    def test_normalize_prefers_b2b_over_permanent(
        self, justjoin_full_offer: dict[str, Any]
    ) -> None:
        # Fixture ma w kolejnosci b2b (8-13k) i permanent (7-11k) —
        # scraper musi wybrac b2b niezaleznie od kolejnosci.
        reversed_offer = copy.deepcopy(justjoin_full_offer)
        reversed_offer["employmentTypes"] = list(reversed(reversed_offer["employmentTypes"]))

        offer = JustJoinScraper().normalize(reversed_offer)

        assert offer.salary is not None
        assert offer.salary.contract == "b2b"
        assert offer.salary.min == 8000

    def test_normalize_url_fallback_from_slug(self, justjoin_full_offer: dict[str, Any]) -> None:
        modified = copy.deepcopy(justjoin_full_offer)
        modified.pop("link", None)

        offer = JustJoinScraper().normalize(modified)

        assert offer.url == f"https://justjoin.it/job-offer/{modified['slug']}"

    def test_normalize_unknown_workplace_type_is_none(
        self, justjoin_full_offer: dict[str, Any]
    ) -> None:
        modified = copy.deepcopy(justjoin_full_offer)
        modified["workplaceType"] = "atlantis"

        offer = JustJoinScraper().normalize(modified)

        assert offer.work_mode is None


class TestFetch:
    @respx.mock
    async def test_fetch_uses_mocked_api(self, justjoin_sample: dict[str, Any]) -> None:
        # Pierwsza strona — pelna; druga strona pusta zeby przerwac petle.
        route = respx.get(host="api.justjoin.it").mock(
            side_effect=[
                httpx.Response(200, json=justjoin_sample),
                httpx.Response(200, json={"data": [], "meta": {}}),
            ]
        )

        offers = await JustJoinScraper().fetch(SearchParams(keywords=("python",), limit=10))

        assert route.called
        assert len(offers) == 3
        assert all(isinstance(o, JobOffer) for o in offers)
        assert all(o.portal == "justjoin.it" for o in offers)

    @respx.mock
    async def test_fetch_respects_limit(self, justjoin_sample: dict[str, Any]) -> None:
        respx.get(host="api.justjoin.it").mock(
            return_value=httpx.Response(200, json=justjoin_sample)
        )

        offers = await JustJoinScraper().fetch(SearchParams(limit=2))

        assert len(offers) == 2

    @respx.mock
    async def test_fetch_retries_on_500(self, justjoin_sample: dict[str, Any]) -> None:
        respx.get(host="api.justjoin.it").mock(
            side_effect=[
                httpx.Response(500),
                httpx.Response(500),
                httpx.Response(200, json=justjoin_sample),
                httpx.Response(200, json={"data": [], "meta": {}}),
            ]
        )

        offers = await JustJoinScraper().fetch(SearchParams(limit=10))

        assert len(offers) == 3

    @respx.mock
    async def test_fetch_timeout_raises(self) -> None:
        respx.get(host="api.justjoin.it").mock(side_effect=httpx.TimeoutException("slow"))

        with pytest.raises(ScraperTimeoutError):
            await JustJoinScraper().fetch(SearchParams(limit=10))

    @respx.mock
    async def test_fetch_404_raises_http_error(self) -> None:
        respx.get(host="api.justjoin.it").mock(return_value=httpx.Response(404))

        with pytest.raises(ScraperHTTPError):
            await JustJoinScraper(enable_frontend_fallback=False).fetch(SearchParams(limit=10))

    @respx.mock
    async def test_fetch_falls_back_to_frontend_payload(
        self,
        justjoin_full_offer: dict[str, Any],
    ) -> None:
        api_route = respx.get(host="api.justjoin.it").mock(return_value=httpx.Response(404))
        payload = {"pages": [{"data": [justjoin_full_offer]}], "pageParams": [None]}
        escaped_payload = json.dumps(payload, ensure_ascii=False).replace('"', r"\"")
        frontend_route = respx.get(host="justjoin.it").mock(
            return_value=httpx.Response(
                200,
                text=f'<script>self.__next_f.push([1,"{escaped_payload}"])</script>',
            )
        )

        offers = await JustJoinScraper().fetch(SearchParams(keywords=("python",), limit=10))

        assert api_route.called
        assert frontend_route.called
        assert len(offers) == 1
        assert offers[0].location == "Wrocław"

    @respx.mock
    async def test_fetch_frontend_fallback_uses_keyword_query(
        self,
        justjoin_full_offer: dict[str, Any],
    ) -> None:
        respx.get(host="api.justjoin.it").mock(return_value=httpx.Response(404))
        payload = {"pages": [{"data": [justjoin_full_offer]}], "pageParams": [None]}
        escaped_payload = json.dumps(payload, ensure_ascii=False).replace('"', r"\"")
        keyword_frontend_route = respx.get(
            "https://justjoin.it/job-offers/all-locations?keyword=pmo%20specialist"
        ).mock(
            return_value=httpx.Response(
                200,
                text=f'<script>self.__next_f.push([1,"{escaped_payload}"])</script>',
            )
        )

        offers = await JustJoinScraper().fetch(SearchParams(keywords=("PMO Specialist",), limit=10))

        assert keyword_frontend_route.called
        assert len(offers) == 1

    @respx.mock
    async def test_fetch_builds_query_with_seniority_and_keywords(
        self, justjoin_sample: dict[str, Any]
    ) -> None:
        route = respx.get(host="api.justjoin.it").mock(
            return_value=httpx.Response(200, json=justjoin_sample)
        )

        await JustJoinScraper().fetch(
            SearchParams(keywords=("python", "fastapi"), seniority="senior", limit=5)
        )

        called_url = str(route.calls[0].request.url)
        assert "keyword=python+fastapi" in called_url or "keyword=python%20fastapi" in called_url
        assert "experience-level=senior" in called_url

    @respx.mock
    async def test_fetch_sends_realistic_user_agent(self, justjoin_sample: dict[str, Any]) -> None:
        route = respx.get(host="api.justjoin.it").mock(
            return_value=httpx.Response(200, json=justjoin_sample)
        )

        await JustJoinScraper().fetch(SearchParams(limit=5))

        ua = route.calls[0].request.headers.get("user-agent", "")
        assert "Mozilla" in ua and "Chrome" in ua

    @respx.mock
    async def test_fetch_handles_bare_list_response(self, justjoin_sample: dict[str, Any]) -> None:
        # Stara wersja API zwracala czysta liste — sprawdzamy backward compat.
        respx.get(url=API_URL, params={"orderBy": "DESC", "sortBy": "newest", "page": "1"}).mock(
            return_value=httpx.Response(200, json=justjoin_sample["data"])
        )

        offers = await JustJoinScraper().fetch(SearchParams(limit=10))

        assert len(offers) == 3

    def test_extract_offers_from_frontend_html(self, justjoin_full_offer: dict[str, Any]) -> None:
        payload = {"pages": [{"data": [justjoin_full_offer]}], "pageParams": [None]}
        escaped_payload = json.dumps(payload, ensure_ascii=False).replace('"', r"\"")
        html = f'<script>self.__next_f.push([1,"{escaped_payload}"])</script>'

        offers = _extract_offers_from_frontend_html(html)

        assert len(offers) == 1
        assert offers[0]["title"] == "Junior+/Mid Frontend Developer"
