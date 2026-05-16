from __future__ import annotations

import asyncio

from src.scrapers import SearchParams, TheProtocolScraper


async def main() -> None:
    offers = await TheProtocolScraper().fetch(SearchParams(keywords=("python",), limit=10))
    for offer in offers:
        print(f"{offer.title} | {offer.company} | {offer.location} | {offer.url}")


if __name__ == "__main__":
    asyncio.run(main())
