from src.matching.compare import JDParsed, MatchScore, score_match
from src.matching.dedup import DedupedOffer, deduplicate
from src.matching.pipeline import MatchedOffer, run_matching

__all__ = [
    "DedupedOffer",
    "JDParsed",
    "MatchedOffer",
    "MatchScore",
    "deduplicate",
    "run_matching",
    "score_match",
]
