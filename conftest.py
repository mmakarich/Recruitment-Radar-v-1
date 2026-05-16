"""Wspolne fixture dla testow.

Trzymamy je tutaj, zeby kazdy test_*.py mogl uzywac bez importow.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def justjoin_sample() -> dict[str, Any]:
    """Sample odpowiedzi z api.justjoin.it z 3 ofertami."""
    return json.loads((FIXTURES_DIR / "justjoin_sample.json").read_text(encoding="utf-8"))


@pytest.fixture
def justjoin_full_offer(justjoin_sample: dict[str, Any]) -> dict[str, Any]:
    """Pierwsza oferta z fixture — kompletna, z wynagrodzeniem i lokalizacja."""
    offers: list[dict[str, Any]] = justjoin_sample["data"]
    return offers[0]
