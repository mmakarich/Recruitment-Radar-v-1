"""Scraper dla theprotocol.it.

Portal renderuje listingi jako aplikację Next.js. Scraper pobiera HTML,
wyciąga JSON z `<script id="__NEXT_DATA__">`, znajduje listę ofert w strukturze
props i mapuje rekordy na wspólny model JobOffer.

Parser jest defensywny, bo struktury Next.js potrafią zmieniać ścieżki między
deployami frontendu.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import settings
from src.scrapers.base import (
    BaseScraper,
    ContractKind,
    JobOffer,
    SalaryPeriod,
    SalaryRange,
    ScraperHTTPError,
    ScraperStructureChangedError,
    ScraperTimeoutError,
    SearchParams,
    Seniority,
    WorkMode,
)

BASE_URL = "https://theprotocol.it"
DETAIL_URL_TEMPLATE = "https://theprotocol.it/szczegoly/praca/{slug}"

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}

_WORK_MODE_MAP: dict[str, WorkMode] = {
    "remote": "remote",
    "zdalna": "remote",
    "fully_remote": "remote",
    "hybrid": "hybrid",
    "hybrydowa": "hybrid",
    "partly_remote": "hybrid",
    "office": "onsite",
    "full_office": "onsite",
    "onsite": "onsite",
    "stacjonarna": "onsite",
}

_SENIORITY_MAP: dict[str, Seniority] = {
    "junior": "junior",
    "mid": "mid",
    "middle": "mid",
    "regular": "mid",
    "senior": "senior",
    "lead": "lead",
    "expert": "expert",
}

_CONTRACT_MAP: dict[str, ContractKind] = {
    "b2b": "b2b",
    "uop": "uop",
    "permanent": "uop",
    "employment_contract": "uop",
    "contract_of_employment": "uop",
}


class TheProtocolScraper(BaseScraper):
    portal_name = "theprotocol.it"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def fetch(self, params: SearchParams) -> list[JobOffer]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=settings.SCRAPER_TIMEOUT_S,
            headers=_HEADERS,
        )

        try:
            raw_offers = await self._fetch_paginated(client, params)
        finally:
            if owns_client:
                await client.aclose()

        return [self.normalize(raw) for raw in raw_offers[: params.limit]]

    async def _fetch_paginated(
        self,
        client: httpx.AsyncClient,
        params: SearchParams,
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        page = 1

        while len(collected) < params.limit:
            url = self._build_url(params, page)
            html = await self._fetch_one(client, url)
            next_data = extract_next_data_from_html(html)
            offers = extract_offers_from_next_data(next_data)

            if not offers:
                break

            collected.extend(offers)

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
    async def _fetch_one(self, client: httpx.AsyncClient, url: str) -> str:
        try:
            response = await client.get(url)
        except httpx.TimeoutException as exc:
            raise ScraperTimeoutError(f"Timeout pobierając {url}") from exc

        if response.status_code >= 500:
            raise ScraperHTTPError(f"{response.status_code} z {url}")
        if response.status_code >= 400:
            raise ScraperHTTPError(f"{response.status_code} z {url}: {response.text[:200]}")

        return response.text

    @staticmethod
    def _build_url(params: SearchParams, page: int) -> str:
        keyword = params.keywords[0] if params.keywords else "python"
        encoded_keyword = quote(keyword.strip().lower())
        base = f"{BASE_URL}/filtry/{encoded_keyword};t"

        query_parts: list[str] = []
        if params.location:
            query_parts.append(f"city={quote(params.location)}")
        if params.seniority:
            query_parts.append(f"seniority={quote(params.seniority.lower())}")
        if page > 1:
            query_parts.append(f"pageNumber={page}")

        return f"{base}?{'&'.join(query_parts)}" if query_parts else base

    def normalize(self, raw: dict[str, Any]) -> JobOffer:
        slug = _extract_slug(raw)
        return JobOffer(
            title=_extract_title(raw),
            company=_extract_company(raw),
            portal=self.portal_name,
            url=_extract_url(raw, slug),
            location=_extract_location(raw),
            work_mode=_extract_work_mode(raw),
            seniority=_extract_seniority(raw),
            tech_stack=tuple(_extract_tech_stack(raw)),
            salary=_extract_salary(raw),
            published_at=_parse_published_at(
                raw.get("posted")
                or raw.get("publishedAt")
                or raw.get("publicationDate")
                or raw.get("validFrom")
            ),
            scraped_at=datetime.now(UTC),
            raw=raw,
        )


def extract_next_data_from_html(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")

    if not isinstance(script, Tag):
        raise ScraperStructureChangedError("Missing __NEXT_DATA__ script")

    raw_json = script.string or script.get_text()
    if not raw_json:
        raise ScraperStructureChangedError("Empty __NEXT_DATA__ script")

    try:
        return cast("dict[str, Any]", json.loads(raw_json))
    except json.JSONDecodeError as exc:
        raise ScraperStructureChangedError("Invalid __NEXT_DATA__ JSON") from exc


def extract_offers_from_next_data(next_data: dict[str, Any]) -> list[dict[str, Any]]:
    page_props = _dig(next_data, ("props", "pageProps"))
    if isinstance(page_props, dict):
        direct = _extract_offer_list_from_mapping(page_props)
        if direct:
            return direct

    recursive = _find_first_offer_list(next_data)
    return recursive or []


def _extract_offer_list_from_mapping(mapping: dict[str, Any]) -> list[dict[str, Any]]:
    candidate_keys = ("jobOffers", "offers", "items", "results", "data", "jobs", "listings")

    for key in candidate_keys:
        value = mapping.get(key)
        if isinstance(value, list) and _looks_like_offer_list(value):
            return cast("list[dict[str, Any]]", value)
        if isinstance(value, dict):
            nested = _extract_offer_list_from_mapping(value)
            if nested:
                return nested

    return []


def _find_first_offer_list(value: Any) -> list[dict[str, Any]] | None:
    if isinstance(value, list) and _looks_like_offer_list(value):
        return cast("list[dict[str, Any]]", value)

    if isinstance(value, dict):
        for nested_value in value.values():
            found = _find_first_offer_list(nested_value)
            if found:
                return found

    if isinstance(value, list):
        for item in value:
            found = _find_first_offer_list(item)
            if found:
                return found

    return None


def _looks_like_offer_list(value: list[Any]) -> bool:
    if not value:
        return False
    first = value[0]
    return isinstance(first, dict) and (
        "title" in first
        or "position" in first
        or "jobTitle" in first
        or "slug" in first
        or "employer" in first
    )


def _dig(mapping: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = mapping
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _as_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _extract_title(raw: dict[str, Any]) -> str:
    return _as_str(raw.get("title") or raw.get("position") or raw.get("jobTitle"))


def _extract_company(raw: dict[str, Any]) -> str:
    employer = raw.get("employer") or raw.get("company")
    if isinstance(employer, dict):
        return _as_str(employer.get("name"))
    return _as_str(raw.get("companyName") or employer)


def _extract_slug(raw: dict[str, Any]) -> str:
    for key in ("slug", "url", "offerSlug", "seoSlug"):
        value = raw.get(key)
        if isinstance(value, str) and value:
            return value.strip().strip("/")
    return ""


def _extract_url(raw: dict[str, Any], slug: str) -> str:
    for key in ("url", "offerUrl", "jobUrl"):
        value = raw.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value

    if slug.startswith("szczegoly/"):
        return f"{BASE_URL}/{slug}"

    return DETAIL_URL_TEMPLATE.format(slug=slug)


def _extract_location(raw: dict[str, Any]) -> str | None:
    for key in ("workplaces", "locations", "places"):
        value = raw.get(key)
        if isinstance(value, list):
            names: list[str] = []
            for item in value:
                name = _place_name(item)
                if name is not None:
                    names.append(name)
            if names:
                return ", ".join(names)

    location = raw.get("location")
    if isinstance(location, dict):
        name = _place_name(location)
        if name:
            return name
    if isinstance(location, str) and location:
        return location

    return None


def _place_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        city = value.get("city") or value.get("name")
        region = value.get("region") or value.get("province")
        if isinstance(city, str) and isinstance(region, str) and region:
            return f"{city}, {region}"
        if isinstance(city, str) and city:
            return city
    return None


def _extract_work_mode(raw: dict[str, Any]) -> WorkMode | None:
    for key in ("workMode", "workingMode", "workplaceType", "remote"):
        value = raw.get(key)
        if isinstance(value, bool):
            return "remote" if value else None
        if isinstance(value, str):
            mapped = _WORK_MODE_MAP.get(value.lower())
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
    for key in ("technologies", "technology", "requiredSkills", "skills"):
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
    salary = raw.get("salary") or raw.get("salaryRange") or raw.get("salaryRanges")
    contract_types = raw.get("contractTypes") or raw.get("contracts")

    candidates: list[dict[str, Any]] = []
    if isinstance(salary, list):
        candidates = [item for item in salary if isinstance(item, dict)]
    elif isinstance(salary, dict):
        ranges = salary.get("ranges")
        if isinstance(ranges, list):
            candidates = [item for item in ranges if isinstance(item, dict)]
        else:
            candidates = [salary]

    for candidate in candidates:
        extracted = _salary_from_candidate(candidate, contract_types)
        if extracted is not None:
            return extracted

    return None


def _salary_from_candidate(candidate: dict[str, Any], contract_types: Any) -> SalaryRange | None:
    contract = _extract_contract(candidate, contract_types)
    if contract is None:
        return None

    salary_min = candidate.get("min") or candidate.get("from") or candidate.get("lower")
    salary_max = candidate.get("max") or candidate.get("to") or candidate.get("upper")
    if salary_min is None or salary_max is None:
        return None

    unit = str(candidate.get("period") or candidate.get("unit") or "month").lower()
    period: SalaryPeriod = "hour" if unit in ("hour", "h", "hr", "godz") else "month"
    currency = str(candidate.get("currency") or "PLN").upper()

    try:
        return SalaryRange(
            min=int(salary_min),
            max=int(salary_max),
            currency=currency,
            period=period,
            contract=contract,
        )
    except (TypeError, ValueError):
        return None


def _extract_contract(candidate: dict[str, Any], contract_types: Any) -> ContractKind | None:
    raw_contract = (
        candidate.get("contract") or candidate.get("type") or candidate.get("contractType")
    )
    if isinstance(raw_contract, str):
        mapped = _CONTRACT_MAP.get(raw_contract.lower())
        if mapped:
            return mapped

    if isinstance(contract_types, list):
        for item in contract_types:
            value = item.get("type") if isinstance(item, dict) else item
            if isinstance(value, str):
                mapped = _CONTRACT_MAP.get(value.lower())
                if mapped:
                    return mapped

    if isinstance(contract_types, str):
        return _CONTRACT_MAP.get(contract_types.lower())

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
