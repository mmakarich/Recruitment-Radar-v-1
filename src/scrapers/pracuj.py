"""Scraper dla pracuj.pl.

Decyzja techniczna:
Pracuj.pl bywa dynamicznie renderowany i ma mechanizmy antybotowe, dlatego
scraper używa Playwrighta jako podstawowej ścieżki pobierania listingów.
Kod normalize() i parser wynagrodzenia są izolowane, żeby większość logiki
testować jednostkowo bez uruchamiania przeglądarki.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

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

BASE_URL = "https://www.pracuj.pl"
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_WORK_MODE_MAP: dict[str, WorkMode] = {
    "zdalna": "remote",
    "remote": "remote",
    "praca zdalna": "remote",
    "hybrydowa": "hybrid",
    "hybrid": "hybrid",
    "praca hybrydowa": "hybrid",
    "stacjonarna": "onsite",
    "office": "onsite",
    "praca stacjonarna": "onsite",
}

_SENIORITY_MAP: dict[str, Seniority] = {
    "junior": "junior",
    "młodszy": "junior",
    "mid": "mid",
    "regular": "mid",
    "specjalista": "mid",
    "senior": "senior",
    "starszy": "senior",
    "lead": "lead",
    "lider": "lead",
    "expert": "expert",
    "ekspert": "expert",
}

_CONTRACT_KEYWORDS: dict[str, ContractKind] = {
    "b2b": "b2b",
    "kontrakt": "b2b",
    "uop": "uop",
    "umowa o pracę": "uop",
    "umowa o prace": "uop",
}

_CURRENCY_MAP = {
    "zł": "PLN",
    "pln": "PLN",
    "eur": "EUR",
    "€": "EUR",
    "usd": "USD",
    "$": "USD",
}


class PracujScraper(BaseScraper):
    portal_name = "pracuj.pl"

    async def fetch(self, params: SearchParams) -> list[JobOffer]:
        url = self._build_url(params)

        try:
            html = await _fetch_listing_html_with_playwright(url)
        except PlaywrightTimeoutError as exc:
            raise ScraperTimeoutError(f"Timeout pobierając {url}") from exc

        raw_offers = extract_offers_from_html(html)
        return [self.normalize(raw) for raw in raw_offers[: params.limit]]

    @staticmethod
    def _build_url(params: SearchParams) -> str:
        keyword = params.keywords[0] if params.keywords else "python"
        encoded_keyword = quote(keyword.strip().lower())
        return f"{BASE_URL}/praca/{encoded_keyword};kw"

    def normalize(self, raw: dict[str, Any]) -> JobOffer:
        return JobOffer(
            title=_as_str(raw.get("title")),
            company=_as_str(raw.get("company")),
            portal=self.portal_name,
            url=_normalize_url(_as_str(raw.get("url"))),
            location=_none_if_empty(_as_str(raw.get("location"))),
            work_mode=_extract_work_mode(raw),
            seniority=_extract_seniority(raw),
            tech_stack=tuple(_extract_tech_stack(raw)),
            salary=parse_salary_string(_as_str(raw.get("salary"))),
            published_at=_parse_published_at(raw.get("publishedAt")),
            scraped_at=datetime.now(UTC),
            raw=raw,
        )


async def _fetch_listing_html_with_playwright(url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=_USER_AGENT,
            locale="pl-PL",
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            if response is not None and response.status >= 400:
                raise ScraperHTTPError(f"{response.status} z {url}")

            await page.wait_for_timeout(1_000)
            await _scroll_page(page)
            return await page.content()
        finally:
            await context.close()
            await browser.close()


async def _scroll_page(page: Any) -> None:
    for _ in range(3):
        await page.mouse.wheel(0, 1200)
        await asyncio.sleep(0.4)


def extract_offers_from_html(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select('[data-test="default-offer"], [data-test="offer"], article')

    offers: list[dict[str, Any]] = []
    for card in cards:
        title = _select_text(card, ['[data-test="offer-title"]', "h2", "h3"])
        company = _select_text(card, ['[data-test="offer-company"]', '[data-test="company-name"]'])
        location = _select_text(card, ['[data-test="offer-location"]', '[data-test="location"]'])
        salary = _select_text(card, ['[data-test="offer-salary"]', '[data-test="salary"]'])
        href = _select_href(card, ['a[data-test="link-offer"]', "a[href]"])
        tags = _select_many_text(card, ["li", "span"])

        if title or href:
            offers.append(
                {
                    "title": title,
                    "company": company,
                    "location": location,
                    "salary": salary,
                    "url": href,
                    "tags": tags,
                    "publishedAt": None,
                }
            )

    return offers


def parse_salary_string(value: str) -> SalaryRange | None:
    text = value.strip().lower()
    if not text:
        return None

    normalized = text.replace("\u00a0", " ").replace("–", "-").replace("—", "-").replace(" ", "")

    numbers = [int(match.replace(",", ".")) for match in re.findall(r"\d+(?:[,.]\d+)?", normalized)]
    if not numbers:
        return None

    if len(numbers) == 1:
        salary_min = salary_max = numbers[0]
    else:
        salary_min, salary_max = numbers[0], numbers[1]

    currency = "PLN"
    for marker, mapped in _CURRENCY_MAP.items():
        if marker in text:
            currency = mapped
            break

    period: SalaryPeriod = (
        "hour" if any(token in text for token in ("/h", "godz", "hour")) else "month"
    )
    contract = _extract_contract_from_text(text)

    return SalaryRange(
        min=salary_min,
        max=salary_max,
        currency=currency,
        period=period,
        contract=contract,
    )


def _extract_contract_from_text(text: str) -> ContractKind:
    for marker, contract in _CONTRACT_KEYWORDS.items():
        if marker in text:
            return contract
    return "uop"


def _select_text(card: Any, selectors: list[str]) -> str:
    for selector in selectors:
        element = card.select_one(selector)
        if element is not None:
            text = element.get_text(" ", strip=True)
            if text:
                return str(text)
    return ""


def _select_many_text(card: Any, selectors: list[str]) -> list[str]:
    values: list[str] = []
    for selector in selectors:
        for element in card.select(selector):
            text = element.get_text(" ", strip=True)
            if text:
                values.append(text)
    return values


def _select_href(card: Any, selectors: list[str]) -> str:
    for selector in selectors:
        element = card.select_one(selector)
        if element is not None:
            href = element.get("href")
            if isinstance(href, str) and href:
                return href
    return ""


def _normalize_url(value: str) -> str:
    if not value:
        return BASE_URL
    if value.startswith("http"):
        return value
    if value.startswith("/"):
        return f"{BASE_URL}{value}"
    return f"{BASE_URL}/{value}"


def _extract_work_mode(raw: dict[str, Any]) -> WorkMode | None:
    candidates = [_as_str(raw.get("work_mode")), _as_str(raw.get("workMode"))]
    candidates.extend(_extract_tags(raw))

    for candidate in candidates:
        lowered = candidate.lower()
        for marker, mapped in _WORK_MODE_MAP.items():
            if marker in lowered:
                return mapped

    return None


def _extract_seniority(raw: dict[str, Any]) -> Seniority | None:
    candidates = [_as_str(raw.get("seniority"))]
    candidates.extend(_extract_tags(raw))
    candidates.append(_as_str(raw.get("title")))

    for candidate in candidates:
        lowered = candidate.lower()
        for marker, mapped in _SENIORITY_MAP.items():
            if marker in lowered:
                return mapped

    return None


def _extract_tech_stack(raw: dict[str, Any]) -> list[str]:
    tech = raw.get("tech_stack") or raw.get("skills")
    if isinstance(tech, list):
        return [item for item in tech if isinstance(item, str)]

    tags = _extract_tags(raw)
    common_markers = {
        "python",
        "django",
        "fastapi",
        "sql",
        "aws",
        "azure",
        "java",
        "javascript",
        "react",
        "docker",
        "kubernetes",
    }
    result: list[str] = []
    for tag in tags:
        normalized = tag.strip()
        if normalized.lower() in common_markers:
            result.append(normalized)

    return result


def _extract_tags(raw: dict[str, Any]) -> list[str]:
    tags = raw.get("tags")
    if isinstance(tags, list):
        return [tag for tag in tags if isinstance(tag, str)]
    return []


def _parse_published_at(value: Any) -> datetime:
    if value is None:
        return datetime.now(UTC)

    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return datetime.now(UTC)

    return datetime.now(UTC)


def _as_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _none_if_empty(value: str) -> str | None:
    return value if value else None
