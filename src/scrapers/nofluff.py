"""Scraper dla nofluffjobs.com.

Implementacja jest analogiczna do JustJoinScraper: fetch pobiera JSON,
normalize mapuje rekord portalu na wspólny model JobOffer.

NoFluffJobs okresowo zmienia kształt API, dlatego parser obsługuje kilka
najczęściej spotykanych wariantów nazw pól i struktur list ofert.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlencode

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import settings
from src.scrapers.base import (
    BaseScraper,
    ContractKind,
    JobOffer,
    SalaryPeriod,
    SalaryRange,
    ScraperHTTPError,
    ScraperTimeoutError,
    SearchParams,
    Seniority,
    WorkMode,
)

API_URL = "https://nofluffjobs.com/api/joboffers/main"
OFFER_URL_TEMPLATE = "https://nofluffjobs.com/job/{slug}"

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "application/json",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}

_WORK_MODE_MAP: dict[str, WorkMode] = {
    "remote": "remote",
    "fully_remote": "remote",
    "hybrid": "hybrid",
    "partly_remote": "hybrid",
    "office": "onsite",
    "onsite": "onsite",
}

_SENIORITY_MAP: dict[str, Seniority] = {
    "junior": "junior",
    "trainee": "junior",
    "mid": "mid",
    "regular": "mid",
    "senior": "senior",
    "lead": "lead",
    "expert": "expert",
}

_CONTRACT_MAP: dict[str, ContractKind] = {
    "b2b": "b2b",
    "permanent": "uop",
    "employment_contract": "uop",
    "uop": "uop",
}


class NoFluffScraper(BaseScraper):
    portal_name = "nofluffjobs.com"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def fetch(self, params: SearchParams) -> list[JobOffer]:
        query = self._build_query(params)
        url = f"{API_URL}?{urlencode(query)}" if query else API_URL

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=settings.SCRAPER_TIMEOUT_S,
            headers=_HEADERS,
        )
        try:
            raw_offers = await self._fetch_paginated(client, url, params.limit)
        finally:
            if owns_client:
                await client.aclose()

        return [self.normalize(raw) for raw in raw_offers[: params.limit]]

    async def _fetch_paginated(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        page = 1
        sep = "&" if "?" in base_url else "?"

        while len(collected) < limit:
            page_url = f"{base_url}{sep}page={page}"
            payload = await self._fetch_one(client, page_url)
            offers = _extract_offers(payload)
            if not offers:
                break

            collected.extend(offers)

            if isinstance(payload, list):
                break

            page += 1
            if page > 50:
                break

        return collected

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((ScraperHTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _fetch_one(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        try:
            response = await client.get(url)
        except httpx.TimeoutException as exc:
            raise ScraperTimeoutError(f"Timeout pobierając {url}") from exc

        if response.status_code >= 500:
            raise ScraperHTTPError(f"{response.status_code} z {url}")
        if response.status_code >= 400:
            raise ScraperHTTPError(f"{response.status_code} z {url}: {response.text[:200]}")

        return cast("dict[str, Any] | list[dict[str, Any]]", response.json())

    @staticmethod
    def _build_query(params: SearchParams) -> dict[str, str]:
        query: dict[str, str] = {}
        if params.keywords:
            query["criteria"] = " ".join(params.keywords)
        if params.seniority:
            query["seniority"] = params.seniority.lower()
        if params.location:
            query["city"] = params.location
        query["sort"] = "newest"
        return query

    def normalize(self, raw: dict[str, Any]) -> JobOffer:
        slug = _extract_slug(raw)
        return JobOffer(
            title=_as_str(raw.get("title") or raw.get("position")),
            company=_extract_company(raw),
            portal=self.portal_name,
            url=_extract_url(raw, slug),
            location=_extract_location(raw),
            work_mode=_extract_work_mode(raw),
            seniority=_extract_seniority(raw),
            tech_stack=tuple(_extract_tech_stack(raw)),
            salary=_extract_salary(raw),
            published_at=_parse_published_at(raw.get("posted") or raw.get("publishedAt")),
            scraped_at=datetime.now(UTC),
            raw=raw,
        )


def _extract_offers(payload: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload

    keys = ("data", "postings", "jobs", "jobOffers", "offers", "items", "content", "results")
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return cast("list[dict[str, Any]]", value)

    nested = payload.get("data")
    if isinstance(nested, dict):
        for key in keys:
            value = nested.get(key)
            if isinstance(value, list):
                return cast("list[dict[str, Any]]", value)

    return []


def _as_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _extract_company(raw: dict[str, Any]) -> str:
    company = raw.get("name") or raw.get("company") or raw.get("companyName")
    if isinstance(company, dict):
        return _as_str(company.get("name"))
    return _as_str(company)


def _extract_slug(raw: dict[str, Any]) -> str:
    for key in ("url", "urlFragment", "slug", "postingUrl"):
        value = raw.get(key)
        if isinstance(value, str) and value:
            return value.strip().strip("/")
    return ""


def _extract_url(raw: dict[str, Any], slug: str) -> str:
    for key in ("url", "postingUrl", "jobUrl"):
        value = raw.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    return OFFER_URL_TEMPLATE.format(slug=slug)


def _extract_location(raw: dict[str, Any]) -> str | None:
    location = raw.get("location")
    if isinstance(location, dict):
        places = location.get("places") or location.get("cities")
        if isinstance(places, list):
            location_names: list[str] = []
            for place in places:
                name = _place_name(place)
                if name is not None:
                    location_names.append(name)
            if location_names:
                return ", ".join(location_names)

    places = raw.get("places")
    if isinstance(places, list):
        top_level_place_names: list[str] = []
        for place in places:
            name = _place_name(place)
            if name is not None:
                top_level_place_names.append(name)
        if top_level_place_names:
            return ", ".join(top_level_place_names)

    city = raw.get("city") or raw.get("location")
    if isinstance(city, str) and city:
        return city

    return None


def _place_name(place: Any) -> str | None:
    if isinstance(place, str):
        return place
    if isinstance(place, dict):
        for key in ("city", "name", "value"):
            value = place.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _extract_work_mode(raw: dict[str, Any]) -> WorkMode | None:
    candidates = (
        raw.get("workplaceType"),
        raw.get("workMode"),
        raw.get("remote"),
        raw.get("fullyRemote"),
    )
    for candidate in candidates:
        if isinstance(candidate, bool):
            return "remote" if candidate else None
        if isinstance(candidate, str):
            mapped = _WORK_MODE_MAP.get(candidate.lower())
            if mapped:
                return mapped
    return None


def _extract_seniority(raw: dict[str, Any]) -> Seniority | None:
    value = raw.get("seniority") or raw.get("experienceLevel") or raw.get("level")
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, str):
        return _SENIORITY_MAP.get(value.lower())
    return None


def _extract_tech_stack(raw: dict[str, Any]) -> list[str]:
    for key in ("technology", "technologies", "requiredSkills", "skills"):
        value = raw.get(key)
        if isinstance(value, list):
            result: list[str] = []
            for item in value:
                if isinstance(item, str):
                    result.append(item)
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("value")
                    if isinstance(name, str):
                        result.append(name)
            return result
        if isinstance(value, str):
            return [value]
    return []


def _extract_salary(raw: dict[str, Any]) -> SalaryRange | None:
    salary = raw.get("salary")
    if salary in (None, "", "undisclosed"):
        return None

    candidates: list[dict[str, Any]] = []
    if isinstance(salary, list):
        candidates = [item for item in salary if isinstance(item, dict)]
    elif isinstance(salary, dict):
        ranges = salary.get("ranges")
        if isinstance(ranges, list):
            candidates = [item for item in ranges if isinstance(item, dict)]
        else:
            candidates = [salary]

    priority = {"b2b": 0, "permanent": 1, "employment_contract": 1, "uop": 1}
    candidates = sorted(
        candidates,
        key=lambda item: priority.get(str(item.get("type") or item.get("contract") or ""), 99),
    )

    for item in candidates:
        contract_raw = str(item.get("type") or item.get("contract") or "").lower()
        contract = _CONTRACT_MAP.get(contract_raw)
        if contract is None:
            continue

        salary_min = item.get("min") or item.get("from")
        salary_max = item.get("max") or item.get("to")
        if salary_min is None or salary_max is None:
            continue

        unit = str(item.get("unit") or item.get("period") or "month").lower()
        period: SalaryPeriod = "hour" if unit in ("hour", "h") else "month"
        currency = str(item.get("currency") or "PLN").upper()

        try:
            return SalaryRange(
                min=int(salary_min),
                max=int(salary_max),
                currency=currency,
                period=period,
                contract=contract,
            )
        except (TypeError, ValueError):
            continue

    return None


def _parse_published_at(value: Any) -> datetime:
    if value is None:
        return datetime.now(UTC)

    if isinstance(value, int | float):
        timestamp = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(timestamp, tz=UTC)

    if isinstance(value, str):
        try:
            normalized = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return datetime.now(UTC)

    return datetime.now(UTC)
