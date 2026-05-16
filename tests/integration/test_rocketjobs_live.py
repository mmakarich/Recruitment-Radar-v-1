from __future__ import annotations

import pytest

from src.scrapers import RocketJobsScraper, SearchParams


@pytest.mark.live
async def test_rocketjobs_live_fetch_returns_basic_fields() -> None:
    offers = await RocketJobsScraper().fetch(SearchParams(keywords=("marketing",), limit=5))

    assert len(offers) >= 1
    assert all(offer.title for offer in offers)
    assert all(offer.company for offer in offers)
    assert all(offer.url for offer in offers)
