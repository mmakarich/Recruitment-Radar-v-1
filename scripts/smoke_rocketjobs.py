from __future__ import annotations

import asyncio
import sys

from src.scrapers import RocketJobsScraper, SearchParams


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def main() -> None:
    offers = await RocketJobsScraper().fetch(SearchParams(keywords=("marketing",), limit=10))
    for offer in offers:
        print(f"{offer.title} | {offer.company} | {offer.location} | {offer.url}")


if __name__ == "__main__":
    _configure_stdout()
    asyncio.run(main())
