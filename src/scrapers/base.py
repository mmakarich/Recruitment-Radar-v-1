from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from abc import ABC, abstractmethod


@dataclass(frozen=True, slots=True)
class SalaryRange:
    min: int
    max: int
    currency: str
    period: Literal["month", "hour"]
    contract: Literal["b2b", "uop"]


@dataclass(frozen=True, slots=True)
class JobOffer:
    title: str
    company: str
    portal: str
    url: str
    location: str | None
    work_mode: Literal["remote", "hybrid", "onsite"] | None
    seniority: Literal["junior", "mid", "senior", "lead", "expert"] | None
    tech_stack: list[str]
    salary: SalaryRange | None
    published_at: datetime
    scraped_at: datetime
    raw: dict[str, Any]


@dataclass
class SearchParams:
    keywords: list[str]
    location: str | None
    seniority: str | None
    tech_stack: list[str]
    limit: int = 100


class BaseScraper(ABC):
    portal_name: str

    @abstractmethod
    async def fetch(self, params: SearchParams) -> list[JobOffer]: ...

    @abstractmethod
    def normalize(self, raw: dict) -> JobOffer: ...
