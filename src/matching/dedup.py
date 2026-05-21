from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from src.scrapers.base import JobOffer, SalaryRange

TITLE_WEIGHT = 0.35
COMPANY_WEIGHT = 0.30
LOCATION_WEIGHT = 0.10
SENIORITY_WEIGHT = 0.10
WORK_MODE_WEIGHT = 0.05
TECH_WEIGHT = 0.05
SALARY_WEIGHT = 0.05
UNKNOWN_OPTIONAL_SCORE = 100


@dataclass(frozen=True, slots=True)
class DedupedOffer:
    primary: JobOffer
    duplicates: tuple[JobOffer, ...]
    portals: tuple[str, ...]
    salary_variants: tuple[SalaryRange, ...]
    match_confidence: int


class _UnionFind:
    def __init__(self, size: int) -> None:
        self._parent = list(range(size))

    def find(self, item: int) -> int:
        parent = self._parent[item]
        if parent != item:
            self._parent[item] = self.find(parent)
        return self._parent[item]

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self._parent[right_root] = left_root


def deduplicate(offers: list[JobOffer], threshold: int = 85) -> list[DedupedOffer]:
    if not offers:
        return []

    sorted_offers = sorted(
        offers, key=lambda offer: (_normalize_company(offer.company), offer.title)
    )
    union_find = _UnionFind(len(sorted_offers))

    for left_index, left_offer in enumerate(sorted_offers):
        for right_index in range(left_index + 1, len(sorted_offers)):
            right_offer = sorted_offers[right_index]
            if not _can_be_duplicate(left_offer, right_offer):
                continue
            score = _offer_similarity(left_offer, right_offer)
            if score >= threshold:
                union_find.union(left_index, right_index)

    components: dict[int, list[int]] = {}
    for index in range(len(sorted_offers)):
        root = union_find.find(index)
        components.setdefault(root, []).append(index)

    result = [
        _build_deduped_offer([sorted_offers[index] for index in indexes])
        for indexes in components.values()
    ]
    return sorted(result, key=lambda item: item.primary.published_at, reverse=True)


def _build_deduped_offer(component: list[JobOffer]) -> DedupedOffer:
    primary = max(component, key=lambda offer: (offer.published_at, _salary_max(offer)))
    duplicates = tuple(offer for offer in component if offer is not primary)
    portals = tuple(sorted({offer.portal for offer in component}))

    salary_variants = tuple(
        dict.fromkeys(offer.salary for offer in component if offer.salary is not None)
    )

    return DedupedOffer(
        primary=primary,
        duplicates=duplicates,
        portals=portals,
        salary_variants=salary_variants,
        match_confidence=_component_confidence(component),
    )


def _component_confidence(component: list[JobOffer]) -> int:
    if len(component) <= 1:
        return 100

    scores: list[int] = []
    for left_index, left_offer in enumerate(component):
        for right_index in range(left_index + 1, len(component)):
            scores.append(_offer_similarity(left_offer, component[right_index]))

    return int(round(sum(scores) / len(scores))) if scores else 100


def _salary_max(offer: JobOffer) -> int:
    return offer.salary.max if offer.salary is not None else -1


def _offer_similarity(left: JobOffer, right: JobOffer) -> int:
    title_score = fuzz.token_sort_ratio(_normalize_text(left.title), _normalize_text(right.title))
    company_score = fuzz.token_sort_ratio(
        _normalize_company(left.company),
        _normalize_company(right.company),
    )
    location_score = _location_score(left, right)
    seniority_score = _optional_exact_score(left.seniority, right.seniority)
    work_mode_score = _optional_exact_score(left.work_mode, right.work_mode)
    tech_score = _tech_score(left.tech_stack, right.tech_stack)
    salary_score = _salary_score(left.salary, right.salary)

    return int(
        round(
            title_score * TITLE_WEIGHT
            + company_score * COMPANY_WEIGHT
            + location_score * LOCATION_WEIGHT
            + seniority_score * SENIORITY_WEIGHT
            + work_mode_score * WORK_MODE_WEIGHT
            + tech_score * TECH_WEIGHT
            + salary_score * SALARY_WEIGHT
        )
    )


def _can_be_duplicate(left: JobOffer, right: JobOffer) -> bool:
    if (
        left.seniority is not None
        and right.seniority is not None
        and left.seniority != right.seniority
    ):
        return False
    if (
        left.work_mode is not None
        and right.work_mode is not None
        and left.work_mode != right.work_mode
    ):
        return False
    return not (
        left.work_mode == "onsite"
        and right.work_mode == "onsite"
        and left.location is not None
        and right.location is not None
        and not _locations_overlap(left.location, right.location)
    )


def _optional_exact_score(left: str | None, right: str | None) -> int:
    if left is None or right is None:
        return UNKNOWN_OPTIONAL_SCORE
    return 100 if left == right else 0


def _location_score(left: JobOffer, right: JobOffer) -> int:
    if left.location is None or right.location is None:
        return UNKNOWN_OPTIONAL_SCORE
    if _locations_overlap(left.location, right.location):
        return 100
    return int(
        round(
            fuzz.token_sort_ratio(
                _normalize_text(left.location),
                _normalize_text(right.location),
            )
        )
    )


def _locations_overlap(left: str, right: str) -> bool:
    left_locations = _location_parts(left)
    right_locations = _location_parts(right)
    if not left_locations or not right_locations:
        return False
    return bool(left_locations & right_locations)


def _location_parts(value: str) -> set[str]:
    return {_normalize_text(part) for part in re.split(r"[,;/|]", value) if _normalize_text(part)}


def _tech_score(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    left_set = {_normalize_text(item) for item in left if item}
    right_set = {_normalize_text(item) for item in right if item}
    if not left_set or not right_set:
        return UNKNOWN_OPTIONAL_SCORE
    return int(round((len(left_set & right_set) / len(left_set | right_set)) * 100))


def _salary_score(left: SalaryRange | None, right: SalaryRange | None) -> int:
    if left is None or right is None:
        return UNKNOWN_OPTIONAL_SCORE
    if left.currency != right.currency or left.period != right.period:
        return 0

    overlap_start = max(left.min, right.min)
    overlap_end = min(left.max, right.max)
    if overlap_start > overlap_end:
        return 0

    left_width = left.max - left.min
    right_width = right.max - right.min
    comparable_width = min(left_width, right_width)
    if comparable_width == 0:
        return 100

    return int(round(((overlap_end - overlap_start) / comparable_width) * 100))


def _normalize_company(value: str) -> str:
    normalized = _normalize_text(value)
    normalized = re.sub(
        r"\b(sp\.?\s*z\s*o\.?\s*o\.?|s\.?\s*a\.?|ltd\.?|gmbh|llc|inc\.?)\b",
        "",
        normalized,
    )
    normalized = normalized.replace(".", " ")
    return re.sub(r"\s+", " ", normalized).strip()


def _normalize_text(value: str) -> str:
    lowered = value.lower()
    without_punctuation = re.sub(r"[^\w\s/+.-]", " ", lowered)
    return re.sub(r"\s+", " ", without_punctuation).strip()
