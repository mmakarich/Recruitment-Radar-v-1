from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from src.scrapers.base import JobOffer, SalaryRange


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
    signatures = [_signature(offer) for offer in sorted_offers]

    union_find = _UnionFind(len(sorted_offers))

    for left_index, left_signature in enumerate(signatures):
        for right_index in range(left_index + 1, len(signatures)):
            score = int(round(fuzz.token_sort_ratio(left_signature, signatures[right_index])))
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
    signatures = [_signature(offer) for offer in component]
    for left_index, left_signature in enumerate(signatures):
        for right_index in range(left_index + 1, len(signatures)):
            scores.append(
                int(round(fuzz.token_sort_ratio(left_signature, signatures[right_index])))
            )

    return int(round(sum(scores) / len(scores))) if scores else 100


def _salary_max(offer: JobOffer) -> int:
    return offer.salary.max if offer.salary is not None else -1


def _signature(offer: JobOffer) -> str:
    return f"{_normalize_company(offer.company)} | {_normalize_text(offer.title)}"


def _normalize_company(value: str) -> str:
    normalized = _normalize_text(value)
    normalized = re.sub(
        r"\b(sp\.?\s*z\s*o\.?o\.?|s\.?a\.?|ltd\.?|gmbh|llc|inc\.?)\b",
        "",
        normalized,
    )
    return re.sub(r"\s+", " ", normalized).strip()


def _normalize_text(value: str) -> str:
    lowered = value.lower()
    without_punctuation = re.sub(r"[^\w\s/+.-]", " ", lowered)
    return re.sub(r"\s+", " ", without_punctuation).strip()
