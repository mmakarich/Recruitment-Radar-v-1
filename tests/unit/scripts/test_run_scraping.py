from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from scripts import run_scraping
from src.scrapers.base import JobOffer, SalaryRange, SearchParams


def _offer(
    portal: str = "justjoin.it",
    *,
    title: str = "Senior Python Developer",
    tech_stack: tuple[str, ...] = ("Python", "FastAPI"),
    url_suffix: str | None = None,
) -> JobOffer:
    return JobOffer(
        title=title,
        company="Acme",
        portal=portal,
        url=f"https://example.com/{url_suffix or portal}",
        location="Warszawa",
        work_mode="remote",
        seniority="senior",
        tech_stack=tech_stack,
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


class _MixedScraper:
    portal_name = "mixed"

    async def fetch(self, params: SearchParams) -> list[JobOffer]:
        keyword = params.keywords[0] if params.keywords else "empty"
        return [
            _offer(
                "mixed.pl",
                title=f"{keyword.title()} Consultant",
                tech_stack=(keyword,),
                url_suffix=f"match-{keyword}",
            ),
            _offer(
                "mixed.pl",
                title="Random Accountant",
                tech_stack=("accounting",),
                url_suffix=f"noise-{keyword}",
            ),
        ]


class _PartiallyFailingKeywordScraper:
    portal_name = "partial"

    async def fetch(self, params: SearchParams) -> list[JobOffer]:
        keyword = params.keywords[0]
        if keyword == "broken":
            raise RuntimeError("keyword boom")
        return [
            _offer(
                "partial.pl",
                title=f"{keyword.title()} Consultant",
                tech_stack=(keyword,),
                url_suffix=f"partial-{keyword}",
            )
        ]


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


def test_selected_portals_all_excludes_optional_portals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_scraping, "DEFAULT_PORTALS", ("ok", "empty"))
    monkeypatch.setattr(run_scraping, "OPTIONAL_PORTALS", ("failing",))

    assert run_scraping._selected_portals("all") == ("ok", "empty")


def test_selected_portals_filters_arg() -> None:
    assert run_scraping._selected_portals("ok,empty") == ("ok", "empty")


def test_selected_portals_allows_optional_portal_when_explicit() -> None:
    assert run_scraping._selected_portals("failing") == ("failing",)


def test_selected_portals_unknown_raises() -> None:
    with pytest.raises(ValueError):
        run_scraping._selected_portals("missing")


def test_selected_keywords_explicit_overrides_profile(tmp_path: Path) -> None:
    missing_config = tmp_path / "missing.toml"

    result = run_scraping._selected_keywords(
        keywords_arg="PMO Specialist, SAP, pmo specialist",
        keyword_profile="consulting",
        keyword_config_path=missing_config,
    )

    assert result == ("PMO Specialist", "SAP")


def test_load_keyword_profile_reads_nested_groups(tmp_path: Path) -> None:
    config = tmp_path / "keywords.toml"
    config.write_text(
        """
[profiles.consulting.groups.delivery]
keywords = ["PMO Specialist", "Project Manager"]

[profiles.consulting.groups.erp]
keywords = ["SAP", "SAP"]
""",
        encoding="utf-8",
    )

    result = run_scraping._load_keyword_profile("consulting", config)

    assert result == ("PMO Specialist", "Project Manager", "SAP")


def test_load_keyword_profile_unknown_explains_keywords_field(tmp_path: Path) -> None:
    config = tmp_path / "keywords.toml"
    config.write_text(
        """
[profiles.consulting]
description = "Default"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match='--keywords "Pm"'):
        run_scraping._load_keyword_profile("Pm", config)


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
    assert summary["status"] == "success"

    output_file = tmp_path / "2026-05-16" / "ok.parquet"
    assert output_file.exists()

    df = pd.read_parquet(output_file)
    assert len(df) == 1
    assert df.iloc[0]["title"] == "Senior Python Developer"


@pytest.mark.asyncio
async def test_run_scraping_clears_stale_parquet_files(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "2026-05-16"
    snapshot_dir.mkdir()
    pd.DataFrame([{"title": "Old PM"}]).to_parquet(snapshot_dir / "old.parquet")

    await run_scraping.run_scraping(
        keywords=("python",),
        portals=("ok",),
        limit_per_portal=10,
        output_base_dir=tmp_path,
        snapshot_date=date(2026, 5, 16),
    )

    assert not (snapshot_dir / "old.parquet").exists()
    assert (snapshot_dir / "ok.parquet").exists()


@pytest.mark.asyncio
async def test_run_scraping_batches_keywords_and_filters_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run_scraping, "SCRAPER_REGISTRY", {"mixed": _MixedScraper})

    summary = await run_scraping.run_scraping(
        keywords=("pmo specialist", "sap"),
        portals=("mixed",),
        limit_per_portal=10,
        limit_per_keyword=5,
        output_base_dir=tmp_path,
        snapshot_date=date(2026, 5, 16),
        keyword_profile=None,
    )

    assert summary["total_count"] == 2
    assert summary["keyword_count"] == 2
    assert summary["keyword_metrics"]["pmo specialist"]["fetched_count"] == 2
    assert summary["keyword_metrics"]["pmo specialist"]["matched_count"] == 1
    assert summary["keyword_metrics"]["pmo specialist"]["added_count"] == 1
    assert summary["keyword_metrics"]["pmo specialist"]["filtered_count"] == 1
    assert summary["keyword_metrics"]["sap"]["added_count"] == 1
    assert summary["portals"]["mixed"]["keyword_metrics"][0]["keyword"] == "pmo specialist"
    assert summary["portals"]["mixed"]["keyword_metrics"][0]["duplicate_count"] == 0

    df = pd.read_parquet(tmp_path / "2026-05-16" / "mixed.parquet")
    assert set(df["title"]) == {"Pmo Specialist Consultant", "Sap Consultant"}


@pytest.mark.asyncio
async def test_run_scraping_records_keyword_errors_without_degrading_when_offers_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        run_scraping,
        "SCRAPER_REGISTRY",
        {"partial": _PartiallyFailingKeywordScraper},
    )

    summary = await run_scraping.run_scraping(
        keywords=("python", "broken"),
        portals=("partial",),
        limit_per_portal=10,
        limit_per_keyword=5,
        output_base_dir=tmp_path,
        snapshot_date=date(2026, 5, 16),
    )

    assert summary["status"] == "success"
    assert summary["total_count"] == 1
    assert summary["errors"] == {}
    assert summary["keyword_metrics"]["python"]["added_count"] == 1
    assert summary["keyword_metrics"]["broken"]["errors"]["partial"] == "RuntimeError: keyword boom"
    broken_metric = summary["portals"]["partial"]["keyword_metrics"][1]
    assert broken_metric["error"] == "RuntimeError: keyword boom"


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
    assert summary["failed_portals"] == ["failing"]
    assert summary["status"] == "degraded"
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
    content = summary_path.read_text(encoding="utf-8")
    assert "ok" in content
    assert "empty" in content
    assert '"status": "success"' in content


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


def test_main_returns_one_when_any_scraper_fails(tmp_path: Path) -> None:
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

    assert code == 1
    assert any(tmp_path.iterdir())
