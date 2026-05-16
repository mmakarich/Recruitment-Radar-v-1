"""Fundamenty scrapera: abstract BaseScraper + modele danych.

Decyzje:
- `JobOffer` jest frozen+slots dla taniego hashowania i ochrony przed
  przypadkową mutacją w pipeline.
- `raw: dict` zachowujemy nawet po normalizacji, bo portale dodają nowe
  pola (np. langs, AI tags) i nie chcemy tracić informacji przy dedupe.
- Walidacja `min <= max` w SalaryRange w __post_init__, żeby było blisko
  konstruktora i działało też przy frozen=True.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

WorkMode = Literal["remote", "hybrid", "onsite"]
Seniority = Literal["junior", "mid", "senior", "lead", "expert"]
SalaryPeriod = Literal["month", "hour"]
ContractKind = Literal["b2b", "uop"]


class ScraperError(Exception):
    """Base dla błędów scraperów."""


class ScraperTimeoutError(ScraperError):
    """Portal nie odpowiedział w czasie config.SCRAPER_TIMEOUT_S."""


class ScraperHTTPError(ScraperError):
    """Nieoczekiwany status HTTP (4xx/5xx po retry)."""


@dataclass(frozen=True, slots=True)
class SalaryRange:
    min: int
    max: int
    currency: str
    period: SalaryPeriod
    contract: ContractKind

    def __post_init__(self) -> None:
        if self.min > self.max:
            raise ValueError(f"SalaryRange.min ({self.min}) > max ({self.max})")
        if self.min < 0 or self.max < 0:
            raise ValueError("SalaryRange wartosci musza byc nieujemne")


@dataclass(frozen=True, slots=True)
class JobOffer:
    title: str
    company: str
    portal: str
    url: str
    location: str | None
    work_mode: WorkMode | None
    seniority: Seniority | None
    tech_stack: tuple[str, ...]
    salary: SalaryRange | None
    published_at: datetime
    scraped_at: datetime
    raw: dict[str, Any] = field(hash=False, compare=False, default_factory=dict)


@dataclass(frozen=True, slots=True)
class SearchParams:
    keywords: tuple[str, ...] = ()
    location: str | None = None
    seniority: str | None = None
    tech_stack: tuple[str, ...] = ()
    limit: int = 100


class BaseScraper(ABC):
    """Kontrakt scrapera portalu.

    Implementacje:
    - `portal_name`: krótki identyfikator (np. "justjoin.it").
    - `fetch`: pobiera oferty zgodnie z `SearchParams`, normalizuje i zwraca.
    - `normalize`: czysta funkcja (raw dict -> JobOffer), wygodna do testów
      jednostkowych bez sieci.
    """

    portal_name: str

    @abstractmethod
    async def fetch(self, params: SearchParams) -> list[JobOffer]: ...

    @abstractmethod
    def normalize(self, raw: dict[str, Any]) -> JobOffer: ...
