"""Smoke test scrapera justjoin.it.

Uruchamiaj recznie przed merge'em PR-a — sprawdza ze API odpowiada
i nasze mapowanie produkuje sensowne JobOffer.

    python scripts/smoke_justjoin.py
"""

from __future__ import annotations

import asyncio
import sys

# Pozwalamy odpalac jako `python scripts/smoke_justjoin.py` z roota repo.
sys.path.insert(0, ".")

from src.scrapers import JustJoinScraper, SearchParams  # noqa: E402


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def main() -> int:
    scraper = JustJoinScraper()
    offers = await scraper.fetch(SearchParams(keywords=("python",), limit=10))

    if not offers:
        print("BLAD: zero ofert", file=sys.stderr)
        return 1

    print(f"Pobrano {len(offers)} ofert\n")
    for i, offer in enumerate(offers, 1):
        salary = (
            f"{offer.salary.min}-{offer.salary.max} {offer.salary.currency}/{offer.salary.period}"
            if offer.salary
            else "n/d"
        )
        print(
            f"{i:2}. {offer.title} @ {offer.company} "
            f"| {offer.location or '?'} | {offer.work_mode or '?'} "
            f"| {offer.seniority or '?'} | {salary}"
        )
    return 0


if __name__ == "__main__":
    _configure_stdout()
    sys.exit(asyncio.run(main()))
