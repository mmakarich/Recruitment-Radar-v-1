"""Fundamenty dla wszystkich scraperów portali pracy.

Definiuje wspólny kontrakt: każdy scraper dziedziczy z BaseScraper, normalizuje
dane portalu do JobOffer i implementuje async fetch(). Dzięki temu reszta
pipeline'u (dedup, matching, export) nie zna szczegółów portali.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

# --- Wyjątki ----------------------------------------------------------------


class ScraperError(Exception):
    """Bazowy wyjątek scrapera. Wszystkie pochodne dziedziczą z tego."""


class ScraperTimeoutError(ScraperError):
    """Timeout przy fetch — używane przez scrapery do raportowania problemów sieci."""


class ScraperStructureChangedError(ScraperError):
    """Struktura odpowiedzi portalu się zmieniła — krytyczny sygnał do diagnostyki."""


# --- Dataclasses ------------------------------------------------------------

WorkMode = Literal["remote", "hybrid", "onsite"]
Seniority = Literal["junior", "mid", "senior", "lead", "expert"]
Currency = Literal["PLN", "EUR", "USD"]
Period = Literal["month", "hour"]
Contract = Literal["b2b", "uop"]


@dataclass(frozen=True, slots=True)
class SalaryRange:
    """Widełki wynagrodzenia. Niezmienialne — pomaga w hashowaniu i porównaniach."""

    min: int
    max: int
    currency: Currency
    period: Period
    contract: Contract

    def __post_init__(self) -> None:
        # Walidacja w __post_init__ bo frozen dataclass nie pozwala na __init__
        if self.min < 0 or self.max < 0:
            raise ValueError(f"Salary cannot be negative: min={self.min}, max={self.max}")
        if self.min > self.max:
            raise ValueError(f"Salary min ({self.min}) cannot exceed max ({self.max})")


@dataclass(frozen=True, slots=True)
class JobOffer:
    """Pojedyncza oferta pracy znormalizowana z dowolnego portalu.

    Frozen — żeby można było używać jako klucz w setach/dictach przy deduplikacji.
    Pole `raw` zachowuje oryginalny rekord JSON — przyda się przy debugowaniu
    i przy ewentualnych zmianach mapowania w przyszłości.
    """

    title: str
    company: str
    portal: str
    url: str
    location: str | None
    work_mode: WorkMode | None
    seniority: Seniority | None
    tech_stack: tuple[str, ...]  # tuple zamiast list — frozen dataclass musi być hashable
    salary: SalaryRange | None
    published_at: datetime
    scraped_at: datetime
    raw: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def __post_init__(self) -> None:
        # Wszystkie datetime muszą mieć timezone — łatwiej porównywać snapshoty z różnych dni
        if self.published_at.tzinfo is None:
            raise ValueError("published_at must be timezone-aware (UTC)")
        if self.scraped_at.tzinfo is None:
            raise ValueError("scraped_at must be timezone-aware (UTC)")


@dataclass(frozen=True, slots=True)
class SearchParams:
    """Parametry wyszukiwania przekazywane do scrapera.

    Pola opcjonalne to None — scraper sam decyduje czy mapuje None na "wszystko"
    czy pomija filtr w query stringu.
    """

    keywords: tuple[str, ...] = ()
    location: str | None = None
    seniority: Seniority | None = None
    tech_stack: tuple[str, ...] = ()
    limit: int = 100


# --- Abstract scraper -------------------------------------------------------


class BaseScraper(ABC):
    """Wspólny kontrakt dla wszystkich scraperów portali pracy.

    Każdy konkretny scraper:
    1. Ustawia `portal_name` jako class attribute.
    2. Implementuje async fetch() — wywołania HTTP, paginacja, retry.
    3. Implementuje normalize() — mapowanie surowego dict na JobOffer.

    Logika reszty pipeline'u (dedup, matching, export) zna tylko ten interfejs.
    """

    portal_name: str  # nadpisywane w klasach pochodnych

    @abstractmethod
    async def fetch(self, params: SearchParams) -> list[JobOffer]:
        """Pobiera oferty zgodnie z params i zwraca listę znormalizowanych JobOffer.

        Każda implementacja ma sama obsłużyć retry, paginację i timeouts.
        Powinna rzucać ScraperTimeoutError / ScraperStructureChangedError zamiast
        gołych wyjątków sieciowych.
        """

    @abstractmethod
    def normalize(self, raw: dict[str, Any]) -> JobOffer:
        """Mapuje surowy rekord portalu na JobOffer.

        Wydzielone osobno, żeby można było testować mapowanie bez wywołań HTTP
        (testy normalize z fixtures JSON).
        """


# --- Helpers ----------------------------------------------------------------


def utcnow() -> datetime:
    """datetime.now(UTC) — wydzielone, żeby łatwo mockować w testach."""
    return datetime.now(UTC)
