from __future__ import annotations

from dataclasses import dataclass

from src.matching.compare import JDParsed, MatchScore, score_match
from src.matching.dedup import DedupedOffer, deduplicate
from src.scrapers.base import JobOffer


@dataclass(frozen=True, slots=True)
class MatchedOffer:
    deduped: DedupedOffer
    match_score: MatchScore | None


def run_matching(
    all_offers: list[JobOffer],
    our_offer: JDParsed | None = None,
    dedup_threshold: int = 85,
    min_match_score: int = 0,
    require_tech_overlap: bool = False,
) -> list[MatchedOffer]:
    deduped = deduplicate(all_offers, threshold=dedup_threshold)
    matched: list[MatchedOffer] = []

    for item in deduped:
        match_score = score_match(our_offer, item.primary) if our_offer is not None else None
        if (
            require_tech_overlap
            and our_offer is not None
            and our_offer.tech_stack
            and item.primary.tech_stack
            and match_score is not None
            and match_score.tech_overlap <= 0
        ):
            continue
        if match_score is not None and match_score.total < min_match_score:
            continue
        matched.append(MatchedOffer(deduped=item, match_score=match_score))

    return sorted(
        matched,
        key=lambda item: (
            item.match_score.total if item.match_score is not None else 0,
            item.deduped.primary.published_at,
        ),
        reverse=True,
    )
