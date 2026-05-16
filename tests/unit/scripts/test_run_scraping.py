from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from scripts import run_scraping
from src.scrapers.base import JobOffer, SalaryRange, SearchParams


def _offer(portal: str = "justjoin.it") -> JobOffer:
    return JobOffer(
        title="Senior Python Developer",
        company="Acme",
        portal=portal,
        url=f"https://example.com/{portal}",
        location="Warszawa",
        work_mode="remote",
        seniority="senior",
        tech_stack=("Python", "FastAPI"),
        salary=SalaryRange(
            min=20000,
            max=28000,
            currency="PLN",
            period="month",
            contract="b2b",
        ),
        published_at=datetime(2026, 5, 1, tzinfo=UTC),
        scraped_at=datetime(2026, 5, 16, tzinfo=UTC),
        raw={"id": portal},
    )


class _OkScraper:
    portal_name = "ok"

    async def fetch(self, params: SearchParams) -> list[JobOffer]:
        return [_offer("ok.pl")]


class _EmptyScraper:
    portal_name = "empty"

    async def fetch(self, params: SearchParams) -> list[JobOffer]:
        return []


class _FailingScraper:
    portal_name = "failing"

    async def fetch(self, params: SearchParams) -> list[JobOffer]:
        raise RuntimeError("boom")


@pytest.fixture(autouse=True)
def patch_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        run_scraping,
        "SCRAPER_REGISTRY",
        {
            "ok": _OkScraper,
            "empty": _EmptyScraper,
            "failing": _FailingScraper,
        },
    )
    monkeypatch.setattr(run_scraping, "DEFAULT_PORTALS", ("ok", "empty", "failing"))


def test_selected_portals_all() -> None:
    assert run_scraping._selected_portals("all") == ("ok", "empty", "failing")


def test_selected_portals_filters_arg() -> None:
    assert run_scraping._selected_portals("ok,empty") == ("ok", "empty")


def test_selected_portals_unknown_raises() -> None:
    with pytest.raises(ValueError):
        run_scraping._selected_portals("missing")


@pytest.mark.asyncio
async def test_run_scraping_invokes_selected_scrapers(tmp_path: Path) -> None:
    summary = await run_scraping.run_scraping(
        keywords=("python",),
        portals=("ok",),
        limit_per_portal=10,
        output_base_dir=tmp_path,
        snapshot_date=date(2026, 5, 16),
    )

    assert summary["total_count"] == 1
    assert summary["errors"] == {}

    output_file = tmp_path / "2026-05-16" / "ok.parquet"
    assert output_file.exists()

    df = pd.read_parquet(output_file)
    assert len(df) == 1
    assert df.iloc[0]["title"] == "Senior Python Developer"


@pytest.mark.asyncio
async def test_run_scraping_continues_on_single_scraper_error(tmp_path: Path) -> None:
    summary = await run_scraping.run_scraping(
        keywords=("python",),
        portals=("ok", "failing"),
        limit_per_portal=10,
        output_base_dir=tmp_path,
        snapshot_date=date(2026, 5, 16),
    )

    assert summary["total_count"] == 1
    assert "failing" in summary["errors"]
    assert (tmp_path / "2026-05-16" / "ok.parquet").exists()
    assert (tmp_path / "2026-05-16" / "summary.json").exists()


@pytest.mark.asyncio
async def test_run_scraping_writes_summary_json(tmp_path: Path) -> None:
    await run_scraping.run_scraping(
        keywords=("python",),
        portals=("ok", "empty"),
        limit_per_portal=10,
        output_base_dir=tmp_path,
        snapshot_date=date(2026, 5, 16),
    )

    summary_path = tmp_path / "2026-05-16" / "summary.json"
    assert summary_path.exists()
    content = summary_path.read_text()
    assert "ok" in content
    assert "empty" in content


def test_main_returns_error_code_when_any_scraper_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code = run_scraping.main(
        [
            "--keywords",
            "python",
            "--portals",
            "failing",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert code == 1


def test_main_returns_two_for_unknown_portal(tmp_path: Path) -> None:
    code = run_scraping.main(["--portals", "missing", "--output-dir", str(tmp_path)])

    assert code == 2


def test_main_returns_zero_when_at_least_one_scraper_succeeds(tmp_path: Path) -> None:
    code = run_scraping.main(
        [
            "--keywords",
            "python",
            "--portals",
            "ok,failing",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert code == 0
    assert any(tmp_path.iterdir())
