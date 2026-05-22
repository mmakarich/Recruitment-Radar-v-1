"""Uruchamianie scraperów i zapis snapshotów Parquet.

Skrypt jest używany przez GitHub Actions weekly/on-demand workflow.
Celowo kontynuuje scraping pozostałych portali, nawet jeśli jeden portal padnie.
Na końcu zwraca exit code 1, jeśli wystąpił przynajmniej jeden błąd.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import tomllib
import unicodedata
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, TypedDict

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
DEFAULT_KEYWORD_PROFILE = "consulting"
DEFAULT_KEYWORD_CONFIG = Path("config/scraping_keywords.toml")
DEFAULT_LIMIT_PER_KEYWORD = 50
DEFAULT_PORTALS = ("justjoin", "nofluff", "rocketjobs", "pracuj")
OPTIONAL_PORTALS = ("theprotocol",)

SCRAPER_REGISTRY = {
    "justjoin": JustJoinScraper,
    "nofluff": NoFluffScraper,
    "rocketjobs": RocketJobsScraper,
    "theprotocol": TheProtocolScraper,
    "pracuj": PracujScraper,
}

ScrapingStatus = str


class KeywordMetric(TypedDict, total=False):
    keyword: str
    fetched_count: int
    matched_count: int
    added_count: int
    filtered_count: int
    duplicate_count: int
    elapsed_s: float
    error: str


class ScraperRunResult(TypedDict):
    portal: str
    offers: list[JobOffer]
    error: str | None
    elapsed_s: float
    keyword_metrics: list[KeywordMetric]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Recruitment Radar scraping pipeline")
    parser.add_argument(
        "--keywords",
        default="",
        help="Comma-separated keywords. When provided, they override --keyword-profile.",
    )
    parser.add_argument(
        "--keyword-profile",
        default=DEFAULT_KEYWORD_PROFILE,
        help=(
            "Keyword profile name from config/scraping_keywords.toml. "
            "Ignored when --keywords is set."
        ),
    )
    parser.add_argument(
        "--keyword-config",
        default=str(DEFAULT_KEYWORD_CONFIG),
        help="Path to TOML keyword profile config.",
    )
    parser.add_argument(
        "--limit-per-portal",
        type=int,
        default=200,
        help="Maximum offers per portal",
    )
    parser.add_argument(
        "--limit-per-keyword",
        type=int,
        default=DEFAULT_LIMIT_PER_KEYWORD,
        help="Maximum offers fetched per keyword before local filtering and deduplication.",
    )
    parser.add_argument(
        "--portals",
        default="all",
        help=(
            "Comma-separated portals or 'all'. "
            "'all' runs stable default portals; optional portals must be listed explicitly."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default="data/snapshots",
        help="Base output directory for snapshots",
    )
    return parser.parse_args(argv)


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _dedupe_strings(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = " ".join(value.strip().split())
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            deduped.append(normalized)
    return tuple(deduped)


def _selected_keywords(
    *,
    keywords_arg: str,
    keyword_profile: str | None,
    keyword_config_path: Path,
) -> tuple[str, ...]:
    explicit_keywords = _split_csv(keywords_arg)
    if explicit_keywords:
        return _dedupe_strings(explicit_keywords)

    profile_name = (keyword_profile or "").strip()
    if profile_name:
        return _load_keyword_profile(profile_name, keyword_config_path)

    return DEFAULT_KEYWORDS


def _load_keyword_profile(profile_name: str, config_path: Path) -> tuple[str, ...]:
    try:
        with config_path.open("rb") as file:
            data = tomllib.load(file)
    except FileNotFoundError as exc:
        raise ValueError(f"Keyword profile config not found: {config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid keyword profile config: {config_path}") from exc

    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or profile_name not in profiles:
        available = (
            ", ".join(sorted(str(name) for name in profiles))
            if isinstance(profiles, dict)
            else "none"
        )
        raise ValueError(
            f"Unknown keyword profile: {profile_name}. Available profiles: {available}. "
            f'If you meant a search phrase, pass it via --keywords "{profile_name}".'
        )

    keywords = _collect_keywords(profiles[profile_name])
    if not keywords:
        raise ValueError(f"Keyword profile has no keywords: {profile_name}")
    return _dedupe_strings(tuple(keywords))


def _collect_keywords(value: object) -> list[str]:
    if isinstance(value, dict):
        collected: list[str] = []
        for key, nested in value.items():
            if key == "keywords" and isinstance(nested, list):
                collected.extend(item for item in nested if isinstance(item, str))
            elif isinstance(nested, dict):
                collected.extend(_collect_keywords(nested))
        return collected
    return []


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
    limit_per_keyword: int,
) -> ScraperRunResult:
    started = perf_counter()
    scraper_cls = SCRAPER_REGISTRY[portal]
    scraper = scraper_cls()

    offers: list[JobOffer] = []
    errors: list[str] = []
    keyword_metrics: list[KeywordMetric] = []
    keyword_batches = keywords or ("",)
    try:
        for keyword in keyword_batches:
            keyword_started = perf_counter()
            params = SearchParams(
                keywords=(keyword,) if keyword else (),
                limit=min(limit, limit_per_keyword),
            )
            try:
                batch = await scraper.fetch(params)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                errors.append(f"{keyword or '<empty>'}: {error}")
                keyword_metrics.append(
                    {
                        "keyword": keyword,
                        "fetched_count": 0,
                        "matched_count": 0,
                        "added_count": 0,
                        "filtered_count": 0,
                        "duplicate_count": 0,
                        "elapsed_s": round(perf_counter() - keyword_started, 3),
                        "error": error,
                    }
                )
                continue

            existing_keys = {_offer_identity(offer) for offer in offers}
            matched = [
                offer for offer in batch if not keyword or _offer_matches_keyword(offer, keyword)
            ]
            added: list[JobOffer] = []
            duplicate_count = 0
            for offer in matched:
                key = _offer_identity(offer)
                if key in existing_keys:
                    duplicate_count += 1
                    continue
                existing_keys.add(key)
                added.append(offer)

            offers.extend(added)
            keyword_metrics.append(
                {
                    "keyword": keyword,
                    "fetched_count": len(batch),
                    "matched_count": len(matched),
                    "added_count": len(added),
                    "filtered_count": len(batch) - len(matched),
                    "duplicate_count": duplicate_count,
                    "elapsed_s": round(perf_counter() - keyword_started, 3),
                }
            )
            if len(offers) >= limit:
                break

        error = "; ".join(errors[:3]) if errors and not offers else None
        return {
            "portal": portal,
            "offers": offers[:limit],
            "error": error,
            "elapsed_s": perf_counter() - started,
            "keyword_metrics": keyword_metrics,
        }
    except Exception as exc:
        return {
            "portal": portal,
            "offers": [],
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_s": perf_counter() - started,
            "keyword_metrics": keyword_metrics,
        }


async def run_scraping(
    *,
    keywords: tuple[str, ...],
    portals: tuple[str, ...],
    limit_per_portal: int,
    output_base_dir: Path,
    limit_per_keyword: int = DEFAULT_LIMIT_PER_KEYWORD,
    snapshot_date: date | None = None,
    keyword_profile: str | None = None,
) -> dict[str, Any]:
    snapshot_day = snapshot_date or datetime.now(UTC).date()
    snapshot_dir = output_base_dir / snapshot_day.isoformat()
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    tasks = [
        _run_single_scraper(
            portal=portal,
            keywords=keywords,
            limit=limit_per_portal,
            limit_per_keyword=limit_per_keyword,
        )
        for portal in portals
    ]
    results = await asyncio.gather(*tasks)

    summary: dict[str, Any] = {
        "snapshot_date": snapshot_day.isoformat(),
        "started_at": datetime.now(UTC).isoformat(),
        "keyword_profile": keyword_profile,
        "keywords": list(keywords),
        "keyword_count": len(keywords),
        "limit_per_portal": limit_per_portal,
        "limit_per_keyword": limit_per_keyword,
        "portals": {},
        "keyword_metrics": {keyword: _empty_keyword_summary(keyword) for keyword in keywords},
        "errors": {},
        "failed_portals": [],
        "empty_portals": [],
        "total_count": 0,
    }

    for result in results:
        portal = result["portal"]
        offers = result["offers"]
        error = result["error"]
        elapsed_s = result["elapsed_s"]
        keyword_metrics = result["keyword_metrics"]
        rows = [_offer_to_row(offer) for offer in offers]
        df = pd.DataFrame(rows)

        if rows:
            output_path = snapshot_dir / f"{portal}.parquet"
            df.to_parquet(output_path, index=False)

        summary["portals"][portal] = {
            "count": len(rows),
            "elapsed_s": round(elapsed_s, 3),
            "file": f"{portal}.parquet" if rows else None,
            "keyword_metrics": keyword_metrics,
        }
        _merge_keyword_metrics(summary["keyword_metrics"], portal, keyword_metrics)
        summary["total_count"] += len(rows)

        if error is not None:
            summary["errors"][portal] = error
            summary["failed_portals"].append(portal)
        elif not rows:
            summary["empty_portals"].append(portal)

    summary["finished_at"] = datetime.now(UTC).isoformat()
    summary["status"] = _summary_status(summary)
    summary_path = snapshot_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    return summary


def _empty_keyword_summary(keyword: str) -> dict[str, Any]:
    return {
        "keyword": keyword,
        "fetched_count": 0,
        "matched_count": 0,
        "added_count": 0,
        "filtered_count": 0,
        "duplicate_count": 0,
        "errors": {},
        "portals": {},
    }


def _merge_keyword_metrics(
    summary: dict[str, dict[str, Any]],
    portal: str,
    metrics: list[KeywordMetric],
) -> None:
    for metric in metrics:
        keyword = metric.get("keyword", "")
        keyword_summary = summary.setdefault(keyword, _empty_keyword_summary(keyword))
        portal_metric = {
            "fetched_count": int(metric.get("fetched_count", 0)),
            "matched_count": int(metric.get("matched_count", 0)),
            "added_count": int(metric.get("added_count", 0)),
            "filtered_count": int(metric.get("filtered_count", 0)),
            "duplicate_count": int(metric.get("duplicate_count", 0)),
            "elapsed_s": float(metric.get("elapsed_s", 0.0)),
        }

        for key, value in portal_metric.items():
            if key != "elapsed_s":
                keyword_summary[key] += value

        keyword_summary["portals"][portal] = portal_metric

        error = metric.get("error")
        if error:
            keyword_summary["errors"][portal] = error


def _summary_status(summary: dict[str, Any]) -> ScrapingStatus:
    errors = summary.get("errors", {})
    total_count = int(summary.get("total_count", 0))

    if errors and total_count == 0:
        return "failed"
    if errors:
        return "degraded"
    return "success"


def _dedupe_offers(offers: list[JobOffer]) -> list[JobOffer]:
    seen: set[str] = set()
    deduped: list[JobOffer] = []
    for offer in offers:
        key = _offer_identity(offer)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(offer)
    return deduped


def _offer_identity(offer: JobOffer) -> str:
    if offer.url:
        return f"url:{offer.url.strip().casefold()}"
    return "|".join(
        (
            "fallback",
            offer.portal.casefold(),
            offer.title.casefold(),
            offer.company.casefold(),
            (offer.location or "").casefold(),
        )
    )


def _offer_matches_keyword(offer: JobOffer, keyword: str) -> bool:
    normalized_keyword = _normalize_search_text(keyword)
    if not normalized_keyword:
        return True

    haystack = _normalize_search_text(
        " ".join(
            (
                offer.title,
                offer.company,
                offer.location or "",
                " ".join(offer.tech_stack),
                json.dumps(offer.raw, ensure_ascii=False, default=str),
            )
        )
    )
    if normalized_keyword in haystack:
        return True

    terms = tuple(term for term in normalized_keyword.split() if term)
    if len(terms) > 1:
        return all(_term_matches_haystack(term, haystack) for term in terms)
    return _term_matches_haystack(normalized_keyword, haystack)


def _term_matches_haystack(term: str, haystack: str) -> bool:
    if re.fullmatch(r"[a-z0-9]+", term):
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", haystack) is not None
    return term in haystack


def _normalize_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", ascii_text).strip()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        keywords = _selected_keywords(
            keywords_arg=args.keywords,
            keyword_profile=args.keyword_profile,
            keyword_config_path=Path(args.keyword_config),
        )
        portals = _selected_portals(args.portals)
    except ValueError as exc:
        print(json.dumps({"level": "error", "message": str(exc)}), file=sys.stderr)
        return 2

    summary = asyncio.run(
        run_scraping(
            keywords=keywords,
            portals=portals,
            limit_per_portal=args.limit_per_portal,
            limit_per_keyword=args.limit_per_keyword,
            output_base_dir=Path(args.output_dir),
            keyword_profile=None if args.keywords else args.keyword_profile,
        )
    )

    print(json.dumps(summary, ensure_ascii=False, default=str))

    if summary["status"] != "success":
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
