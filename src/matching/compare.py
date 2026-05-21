from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from src.scrapers.base import JobOffer, SalaryRange, Seniority, WorkMode

TITLE_WEIGHT = 0.30
TECH_WEIGHT = 0.25
SENIORITY_WEIGHT = 0.10
LOCATION_WEIGHT = 0.10
WORK_MODE_WEIGHT = 0.10
COMPANY_WEIGHT = 0.05
SALARY_WEIGHT = 0.10


@dataclass(frozen=True, slots=True)
class JDParsed:
    title: str
    company: str | None = None
    location: str | None = None
    work_mode: WorkMode | None = None
    seniority: Seniority | None = None
    tech_stack: tuple[str, ...] = ()
    salary: SalaryRange | None = None


@dataclass(frozen=True, slots=True)
class MatchScore:
    total: int
    title_score: int
    company_score: int
    salary_score: int
    tech_overlap: float
    seniority_match: bool
    location_match: bool
    work_mode_match: bool
    salary_delta: int | None


def score_match(our: JDParsed, theirs: JobOffer) -> MatchScore:
    title_score = int(round(fuzz.token_sort_ratio(our.title, theirs.title)))
    company_score = _company_score(our.company, theirs.company)
    tech_overlap = _tech_overlap(our.tech_stack, theirs.tech_stack)
    seniority_match = our.seniority is not None and our.seniority == theirs.seniority
    location_match = _location_match(our.location, theirs.location)
    work_mode_match = our.work_mode is not None and our.work_mode == theirs.work_mode
    salary_score = _salary_score(our.salary, theirs.salary)
    salary_delta = _salary_delta(our.salary, theirs.salary)

    total = int(
        round(
            title_score * TITLE_WEIGHT
            + tech_overlap * 100 * TECH_WEIGHT
            + int(seniority_match) * 100 * SENIORITY_WEIGHT
            + int(location_match) * 100 * LOCATION_WEIGHT
            + int(work_mode_match) * 100 * WORK_MODE_WEIGHT
            + company_score * COMPANY_WEIGHT
            + salary_score * SALARY_WEIGHT
        )
    )

    return MatchScore(
        total=max(0, min(100, total)),
        title_score=title_score,
        company_score=company_score,
        salary_score=salary_score,
        tech_overlap=tech_overlap,
        seniority_match=seniority_match,
        location_match=location_match,
        work_mode_match=work_mode_match,
        salary_delta=salary_delta,
    )


def _company_score(our_company: str | None, their_company: str) -> int:
    if our_company is None:
        return 0

    score = int(
        round(
            fuzz.token_sort_ratio(
                _normalize_company(our_company),
                _normalize_company(their_company),
            )
        )
    )
    return score if score >= 80 else 0


def _tech_overlap(ours: tuple[str, ...], theirs: tuple[str, ...]) -> float:
    our_set = {_normalize(item) for item in ours if item}
    their_set = {_normalize(item) for item in theirs if item}

    if not our_set or not their_set:
        return 0.0

    return len(our_set & their_set) / len(our_set | their_set)


def _location_match(our_location: str | None, their_location: str | None) -> bool:
    if our_location is None or their_location is None:
        return False

    our_normalized = _normalize(our_location)
    their_normalized = _normalize(their_location)

    return our_normalized in their_normalized or their_normalized in our_normalized


def _salary_delta(our_salary: SalaryRange | None, their_salary: SalaryRange | None) -> int | None:
    if our_salary is None or their_salary is None:
        return None
    if our_salary.currency != their_salary.currency or our_salary.period != their_salary.period:
        return None
    return their_salary.min - our_salary.min


def _salary_score(our_salary: SalaryRange | None, their_salary: SalaryRange | None) -> int:
    if our_salary is None or their_salary is None:
        return 0
    if our_salary.currency != their_salary.currency or our_salary.period != their_salary.period:
        return 0

    overlap_start = max(our_salary.min, their_salary.min)
    overlap_end = min(our_salary.max, their_salary.max)
    if overlap_start > overlap_end:
        return 0

    our_width = our_salary.max - our_salary.min
    their_width = their_salary.max - their_salary.min
    comparable_width = min(our_width, their_width)
    if comparable_width == 0:
        return 100

    overlap_width = overlap_end - overlap_start
    return int(round((overlap_width / comparable_width) * 100))


def _normalize_company(value: str) -> str:
    normalized = _normalize(value)
    normalized = re.sub(
        r"\b(sp\.?\s*z\s*o\.?\s*o\.?|s\.?\s*a\.?|ltd\.?|gmbh|llc|inc\.?)\b",
        "",
        normalized,
    )
    normalized = normalized.replace(".", " ")
    return re.sub(r"\s+", " ", normalized).strip()


def _normalize(value: str) -> str:
    return " ".join(value.lower().strip().split())
