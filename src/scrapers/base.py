from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

WorkMode = Literal["remote", "hybrid", "onsite"]
Seniority = Literal["junior", "mid", "senior", "lead", "expert"]
SalaryPeriod = Literal["month", "hour"]
ContractKind = Literal["b2b", "uop"]


def utcnow() -> datetime:
    return datetime.now(UTC)


class ScraperError(Exception):
    """Bazowy błąd scrapera."""


class ScraperHTTPError(ScraperError):
    """Błąd HTTP podczas pobierania danych z portalu."""


class ScraperTimeoutError(ScraperError):
    """Timeout podczas pobierania danych z portalu."""


class ScraperStructureChangedError(ScraperError):
    """Portal zmienił strukturę odpowiedzi i parser nie umie jej odczytać."""


@dataclass(frozen=True, slots=True)
class SalaryRange:
    min: int
    max: int
    currency: str
    period: SalaryPeriod
    contract: ContractKind

    def __post_init__(self) -> None:
        if self.min < 0 or self.max < 0:
            raise ValueError("salary cannot be negative")
        if self.min > self.max:
            raise ValueError("min cannot exceed max")


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
    raw: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def __post_init__(self) -> None:
        _ensure_timezone_aware(self.published_at, "published_at")
        _ensure_timezone_aware(self.scraped_at, "scraped_at")


@dataclass(frozen=True, slots=True)
class SearchParams:
    keywords: tuple[str, ...] = ()
    location: str | None = None
    seniority: str | None = None
    tech_stack: tuple[str, ...] = ()
    limit: int = 100


class BaseScraper(ABC):
    portal_name: str

    @abstractmethod
    async def fetch(self, params: SearchParams) -> list[JobOffer]: ...

    @abstractmethod
    def normalize(self, raw: dict[str, Any]) -> JobOffer: ...


def _ensure_timezone_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
