"""Scraper dla justjoin.it.

Używa publicznego JSON API: https://api.justjoin.it/v2/user-panel/offers.
API nie wymaga autoryzacji, ale zwraca 403 bez sensownego User-Agent.

Decyzje:
- Trzymamy fetch wąsko: tylko prosty `keyword` + `experience-level` jako query
  params. Reszta filtrów (location, tech_stack, seniority precyzyjne) dzieje
  się po naszej stronie w pipeline — API justjoin co kilka miesięcy zmienia
  nazwy parametrów i nie chcemy tu wiązać twardych kontraktów.
- Salary: preferujemy `b2b`, fallback do `permanent` (mapowany na "uop").
  Inne typy (mandate, internship, specific_task) -> salary=None, bo nie
  mieszczą się w naszym binarnym podziale b2b/uop.
- Retry tylko na 5xx i timeout. 4xx (np. zmiana schematu, ratelimit) nie
  ma sensu retryować ślepo — szybki fail = szybki sygnał, że coś się zmieniło.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import quote, urlencode

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

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

API_URL = "https://api.justjoin.it/v2/user-panel/offers"
FRONTEND_URL = "https://justjoin.it/job-offers/all-locations"
FRONTEND_URL_TEMPLATE = f"{FRONTEND_URL}?keyword={{keyword}}"
OFFER_URL_TEMPLATE = "https://justjoin.it/job-offer/{slug}"

# Realistyczny UA — justjoin.it odrzuca pusty/python-httpx/* z 403.
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
    "partly_remote": "hybrid",
    "hybrid": "hybrid",
    "office": "onsite",
    "full_office": "onsite",
}

_SENIORITY_MAP: dict[str, Seniority] = {
    "junior": "junior",
    "mid": "mid",
    "senior": "senior",
    "lead": "lead",
    "c-level": "expert",
    "expert": "expert",
}

# Tylko kontrakty, ktore mapuja sie na nasz binarny model b2b/uop.
_CONTRACT_MAP: dict[str, ContractKind] = {
    "b2b": "b2b",
    "permanent": "uop",
    "employment_contract": "uop",
}


class JustJoinScraper(BaseScraper):
    portal_name = "justjoin.it"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        enable_frontend_fallback: bool = True,
    ) -> None:
        # Pozwalamy wstrzyknac klienta dla testow; w produkcji tworzymy nowy
        # per-fetch, zeby connection pool nie zyl miedzy weekly runami.
        self._client = client
        self._enable_frontend_fallback = enable_frontend_fallback

    async def fetch(self, params: SearchParams) -> list[JobOffer]:
        query = self._build_query(params)
        url = f"{API_URL}?{urlencode(query)}" if query else API_URL

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=settings.SCRAPER_TIMEOUT_S, headers=_HEADERS
        )
        try:
            try:
                raw_offers = await self._fetch_paginated(client, url, params.limit)
            except ScraperHTTPError:
                if not self._enable_frontend_fallback:
                    raise
                raw_offers = await self._fetch_frontend(client, params)
        finally:
            if owns_client:
                await client.aclose()

        return [self.normalize(raw) for raw in raw_offers[: params.limit]]

    async def _fetch_frontend(
        self,
        client: httpx.AsyncClient,
        params: SearchParams,
    ) -> list[dict[str, Any]]:
        keyword = params.keywords[0].strip().lower() if params.keywords else ""
        url = (
            FRONTEND_URL_TEMPLATE.format(keyword=quote(keyword, safe=""))
            if keyword
            else FRONTEND_URL
        )
        try:
            response = await client.get(url, headers={**_HEADERS, "Accept": "text/html"})
        except httpx.TimeoutException as exc:
            raise ScraperTimeoutError(f"Timeout pobierajac {url}") from exc

        if response.status_code >= 400:
            raise ScraperHTTPError(f"{response.status_code} z {url}: {response.text[:200]}")

        return _extract_offers_from_frontend_html(response.text)

    async def _fetch_paginated(
        self, client: httpx.AsyncClient, base_url: str, limit: int
    ) -> list[dict[str, Any]]:
        """Pobiera kolejne strony az zbierzemy `limit` ofert lub strona zwroci 0.

        API justjoin v2 zwraca albo czysta liste, albo {data: [...], meta: {...}}.
        Obslugujemy oba ksztalty.
        """
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
            # Jesli odpowiedz nie wyglada na paginowana (czysta lista) — koniec.
            if isinstance(payload, list):
                break
            page += 1
            if page > 50:  # twardy stop, na wypadek niekonczacej sie paginacji
                break
        return collected

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((ScraperHTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _fetch_one(
        self, client: httpx.AsyncClient, url: str
    ) -> dict[str, Any] | list[dict[str, Any]]:
        try:
            response = await client.get(url)
        except httpx.TimeoutException as exc:
            raise ScraperTimeoutError(f"Timeout pobierajac {url}") from exc

        if response.status_code >= 500:
            raise ScraperHTTPError(f"{response.status_code} z {url}")
        if response.status_code >= 400:
            # 4xx nie retryujemy — to sygnal ze schemat sie zmienil albo
            # nas zablokowali. Lepiej fail-fast.
            raise ScraperHTTPError(f"{response.status_code} z {url}: {response.text[:200]}")

        return cast("dict[str, Any] | list[dict[str, Any]]", response.json())

    @staticmethod
    def _build_query(params: SearchParams) -> dict[str, str]:
        query: dict[str, str] = {}
        if params.keywords:
            # API akceptuje pojedynczy `keyword` — laczymy spacja, serwer
            # zwykle traktuje to jak full-text.
            query["keyword"] = " ".join(params.keywords)
        if params.seniority:
            query["experience-level"] = params.seniority.lower()
        if params.location:
            query["city"] = params.location
        query["orderBy"] = "DESC"
        query["sortBy"] = "newest"
        return query

    def normalize(self, raw: dict[str, Any]) -> JobOffer:
        slug = raw.get("slug", "")
        url = raw.get("link") or OFFER_URL_TEMPLATE.format(slug=slug)

        return JobOffer(
            title=raw.get("title", "").strip(),
            company=raw.get("companyName", "").strip(),
            portal=self.portal_name,
            url=url,
            location=_extract_location(raw),
            work_mode=_WORK_MODE_MAP.get(raw.get("workplaceType") or ""),
            seniority=_SENIORITY_MAP.get((raw.get("experienceLevel") or "").lower()),
            tech_stack=tuple(raw.get("requiredSkills") or ()),
            salary=_extract_salary(raw.get("employmentTypes") or []),
            published_at=_parse_published_at(raw.get("publishedAt")),
            scraped_at=datetime.now(UTC),
            raw=raw,
        )


def _extract_offers(payload: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return cast("list[dict[str, Any]]", data)
    return []


def _extract_offers_from_frontend_html(html: str) -> list[dict[str, Any]]:
    decoded = html.replace(r"\"", '"')
    marker_index = decoded.find('"pages"')
    if marker_index == -1:
        return []

    start_index = decoded.rfind("{", 0, marker_index)
    if start_index == -1:
        return []

    try:
        payload, _ = json.JSONDecoder().raw_decode(decoded[start_index:])
    except json.JSONDecodeError:
        return []

    pages = payload.get("pages") if isinstance(payload, dict) else None
    if not isinstance(pages, list):
        return []

    offers: list[dict[str, Any]] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        data = page.get("data")
        if isinstance(data, list):
            offers.extend(item for item in data if isinstance(item, dict))
    return offers


def _extract_location(raw: dict[str, Any]) -> str | None:
    multi = raw.get("multilocation") or []
    if multi:
        cities: list[str] = [
            m["city"]
            for m in multi
            if isinstance(m, dict) and isinstance(m.get("city"), str) and m["city"]
        ]
        if cities:
            return ", ".join(cities)
    # Fallback do legacy pol top-level (starsze oferty czesto je maja).
    city = raw.get("city")
    return cast("str | None", city) if city else None


def _extract_salary(employment_types: list[dict[str, Any]]) -> SalaryRange | None:
    """Wybiera 'najbardziej kanoniczny' wariant placy.

    Preferencja: b2b > uop. Wewnatrz tego samego kontraktu — pierwszy
    rekord z sensownymi from/to.
    """
    # Sortujemy tak, by b2b szedl pierwszy, potem permanent/employment.
    priority = {"b2b": 0, "permanent": 1, "employment_contract": 1}
    candidates = sorted(
        (et for et in employment_types if isinstance(et, dict)),
        key=lambda et: priority.get(et.get("type") or "", 99),
    )

    for et in candidates:
        contract_kind = _CONTRACT_MAP.get(et.get("type") or "")
        if contract_kind is None:
            continue
        salary_from = et.get("from")
        salary_to = et.get("to")
        if salary_from is None or salary_to is None:
            continue
        currency = (et.get("currency") or "PLN").upper()
        unit = et.get("unit") or "month"
        if unit not in ("month", "hour"):
            continue
        period: SalaryPeriod = "hour" if unit == "hour" else "month"
        try:
            return SalaryRange(
                min=int(salary_from),
                max=int(salary_to),
                currency=currency,
                period=period,
                contract=contract_kind,
            )
        except (ValueError, TypeError):
            continue
    return None


def _parse_published_at(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    # justjoin zwraca "2025-02-13T11:22:38.449Z" — fromisoformat w 3.11+
    # akceptuje "Z" jako UTC.
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)
