"""Test live API justjoin.it. Odpalany tylko z `pytest -m live`.

Sluzy do weryfikacji ze nasze mapowanie nadal pasuje do rzeczywistosci.
W CI nie odpalany domyslnie.
"""

from __future__ import annotations

import pytest

from src.scrapers import JustJoinScraper, SearchParams


@pytest.mark.live
async def test_fetch_real_offers() -> None:
    offers = await JustJoinScraper().fetch(SearchParams(keywords=("python",), limit=5))

    assert len(offers) >= 1
    for offer in offers:
        assert offer.title, f"pusty title w {offer}"
        assert offer.company, f"pusty company w {offer}"
        assert offer.url.startswith("https://justjoin.it/"), f"zly url: {offer.url}"
        assert offer.portal == "justjoin.it"
