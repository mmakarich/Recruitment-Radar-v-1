"""Uruchamianie scraperów i zapis snapshotów Parquet.

Skrypt jest używany przez GitHub Actions weekly/on-demand workflow.
Celowo kontynuuje scraping pozostałych portali, nawet jeśli jeden portal padnie.
Na końcu zwraca exit code 1, jeśli wystąpił przynajmniej jeden błąd.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd

from src.scrapers import (
    JustJoinScraper,
    NoFluffScraper,
    PracujScraper,
    RocketJobsScraper,
    SearchParams,
    TheProtocolScraper,
)
from src.scrapers.base import JobOffer, SalaryRange

DEFAULT_KEYWORDS = ("python", "javascript", "react", "java", "devops")
DEFAULT_PORTALS = ("justjoin", "nofluff", "rocketjobs", "theprotocol", "pracuj")

SCRAPER_REGISTRY = {
    "justjoin": JustJoinScraper,
    "nofluff": NoFluffScraper,
    "rocketjobs": RocketJobsScraper,
    "theprotocol": TheProtocolScraper,
    "pracuj": PracujScraper,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Recruitment Radar scraping pipeline")
    parser.add_argument(
        "--keywords",
        default=",".join(DEFAULT_KEYWORDS),
        help="Comma-separated keywords",
    )
    parser.add_argument(
        "--limit-per-portal",
        type=int,
        default=200,
        help="Maximum offers per portal",
    )
    parser.add_argument(
        "--portals",
        default="all",
        help="Comma-separated portals or 'all'",
    )
    parser.add_argument(
        "--output-dir",
        default="data/snapshots",
        help="Base output directory for snapshots",
    )
    return parser.parse_args(argv)


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _selected_portals(value: str) -> tuple[str, ...]:
    if value.strip().lower() == "all":
        return DEFAULT_PORTALS

    selected = _split_csv(value)
    unknown = sorted(set(selected) - set(SCRAPER_REGISTRY))
    if unknown:
        raise ValueError(f"Unknown portals: {', '.join(unknown)}")

    return selected


def _salary_to_dict(salary: SalaryRange | None) -> dict[str, Any] | None:
    if salary is None:
        return None
    return asdict(salary)


def _offer_to_row(offer: JobOffer) -> dict[str, Any]:
    salary = offer.salary
    return {
        "title": offer.title,
        "company": offer.company,
        "portal": offer.portal,
        "url": offer.url,
        "location": offer.location,
        "work_mode": offer.work_mode,
        "seniority": offer.seniority,
        "tech_stack": ",".join(offer.tech_stack),
        "salary_min": salary.min if salary else None,
        "salary_max": salary.max if salary else None,
        "currency": salary.currency if salary else None,
        "period": salary.period if salary else None,
        "contract": salary.contract if salary else None,
        "published_at": offer.published_at.isoformat(),
        "scraped_at": offer.scraped_at.isoformat(),
        "salary": _salary_to_dict(salary),
        "raw": json.dumps(offer.raw, ensure_ascii=False, default=str),
    }


async def _run_single_scraper(
    portal: str,
    keywords: tuple[str, ...],
    limit: int,
) -> tuple[str, list[JobOffer], str | None, float]:
    started = perf_counter()
    scraper_cls = SCRAPER_REGISTRY[portal]
    scraper = scraper_cls()
    params = SearchParams(keywords=keywords, limit=limit)

    try:
        offers = await scraper.fetch(params)
        return portal, offers, None, perf_counter() - started
    except Exception as exc:
        return portal, [], f"{type(exc).__name__}: {exc}", perf_counter() - started


async def run_scraping(
    *,
    keywords: tuple[str, ...],
    portals: tuple[str, ...],
    limit_per_portal: int,
    output_base_dir: Path,
    snapshot_date: date | None = None,
) -> dict[str, Any]:
    snapshot_day = snapshot_date or datetime.now(UTC).date()
    snapshot_dir = output_base_dir / snapshot_day.isoformat()
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    tasks = [
        _run_single_scraper(portal=portal, keywords=keywords, limit=limit_per_portal)
        for portal in portals
    ]
    results = await asyncio.gather(*tasks)

    summary: dict[str, Any] = {
        "snapshot_date": snapshot_day.isoformat(),
        "started_at": datetime.now(UTC).isoformat(),
        "keywords": list(keywords),
        "limit_per_portal": limit_per_portal,
        "portals": {},
        "errors": {},
        "total_count": 0,
    }

    for portal, offers, error, elapsed_s in results:
        rows = [_offer_to_row(offer) for offer in offers]
        df = pd.DataFrame(rows)

        if rows:
            output_path = snapshot_dir / f"{portal}.parquet"
            df.to_parquet(output_path, index=False)

        summary["portals"][portal] = {
            "count": len(rows),
            "elapsed_s": round(elapsed_s, 3),
            "file": f"{portal}.parquet" if rows else None,
        }
        summary["total_count"] += len(rows)

        if error is not None:
            summary["errors"][portal] = error

    summary["finished_at"] = datetime.now(UTC).isoformat()
    summary_path = snapshot_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        keywords = _split_csv(args.keywords)
        portals = _selected_portals(args.portals)
    except ValueError as exc:
        print(json.dumps({"level": "error", "message": str(exc)}), file=sys.stderr)
        return 2

    summary = asyncio.run(
        run_scraping(
            keywords=keywords,
            portals=portals,
            limit_per_portal=args.limit_per_portal,
            output_base_dir=Path(args.output_dir),
        )
    )

    print(json.dumps(summary, ensure_ascii=False, default=str))

    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
