from src.scrapers.base import (
    BaseScraper,
    ContractKind,
    JobOffer,
    SalaryPeriod,
    SalaryRange,
    ScraperError,
    ScraperHTTPError,
    ScraperStructureChangedError,
    ScraperTimeoutError,
    SearchParams,
    Seniority,
    WorkMode,
)
from src.scrapers.justjoin import JustJoinScraper
from src.scrapers.nofluff import NoFluffScraper
from src.scrapers.rocketjobs import RocketJobsScraper

__all__ = [
    "BaseScraper",
    "ContractKind",
    "JobOffer",
    "JustJoinScraper",
    "NoFluffScraper",
    "RocketJobsScraper",
    "SalaryPeriod",
    "SalaryRange",
    "ScraperError",
    "ScraperHTTPError",
    "ScraperStructureChangedError",
    "ScraperTimeoutError",
    "SearchParams",
    "Seniority",
    "WorkMode",
]
