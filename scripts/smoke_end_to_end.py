"""Synthetic end-to-end smoke test for Recruitment Radar.

This script does not call live job boards or Claude API.
It verifies the core product path:

synthetic JobOffer list -> matching pipeline -> Excel export -> DOCX report.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.export import export_to_excel, export_weekly_report
from src.matching.compare import JDParsed
from src.matching.pipeline import MatchedOffer, run_matching
from src.scrapers.base import JobOffer, SalaryRange


def _salary(min_value: int, max_value: int) -> SalaryRange:
    return SalaryRange(
        min=min_value,
        max=max_value,
        currency="PLN",
        period="month",
        contract="b2b",
    )


def _offer(
    *,
    title: str,
    company: str,
    portal: str,
    url: str,
    tech_stack: tuple[str, ...],
    salary: SalaryRange | None,
    seniority: str | None = "senior",
    work_mode: str | None = "remote",
    location: str | None = "Warszawa",
) -> JobOffer:
    return JobOffer(
        title=title,
        company=company,
        portal=portal,
        url=url,
        location=location,
        work_mode=work_mode,  # type: ignore[arg-type]
        seniority=seniority,  # type: ignore[arg-type]
        tech_stack=tech_stack,
        salary=salary,
        published_at=datetime(2026, 5, 16, 8, 0, tzinfo=UTC),
        scraped_at=datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
        raw={"source": "synthetic-smoke"},
    )


def build_sample_jd() -> JDParsed:
    return JDParsed(
        title="Senior Python Developer",
        company="Acme",
        location="Warszawa",
        work_mode="remote",
        seniority="senior",
        tech_stack=("Python", "FastAPI", "AWS"),
        salary=_salary(20000, 26000),
    )


def build_sample_offers() -> list[JobOffer]:
    return [
        _offer(
            title="Senior Python Developer",
            company="Acme Sp. z o.o.",
            portal="justjoin.it",
            url="https://example.com/justjoin/acme-python",
            tech_stack=("Python", "FastAPI", "AWS"),
            salary=_salary(22000, 28000),
        ),
        _offer(
            title="Senior Python Developer",
            company="Acme",
            portal="nofluffjobs.com",
            url="https://example.com/nofluff/acme-python",
            tech_stack=("Python", "FastAPI", "Docker"),
            salary=_salary(21000, 27000),
        ),
        _offer(
            title="Junior React Developer",
            company="Beta",
            portal="rocketjobs.pl",
            url="https://example.com/rocket/beta-react",
            tech_stack=("React", "TypeScript"),
            salary=_salary(9000, 13000),
            seniority="junior",
            work_mode="hybrid",
            location="Kraków",
        ),
    ]


def run_smoke(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    jd = build_sample_jd()
    offers = build_sample_offers()
    matched = run_matching(offers, our_offer=jd, dedup_threshold=85, min_match_score=0)

    excel_path = export_to_excel(
        matched,
        jd,
        output_dir / "recruitment_radar_smoke.xlsx",
    )
    docx_path = export_weekly_report(
        matched,
        jd,
        "2026-W20",
        output_dir / "recruitment_radar_smoke.docx",
    )

    summary = {
        "offers_input": len(offers),
        "matched_count": len(matched),
        "excel_path": str(excel_path),
        "docx_path": str(docx_path),
        "excel_exists": excel_path.exists(),
        "docx_exists": docx_path.exists(),
        "top_score": _top_score(matched),
    }

    if not excel_path.exists() or not docx_path.exists():
        raise RuntimeError(f"Smoke output missing: {summary}")

    if not matched:
        raise RuntimeError("Smoke matching returned no results")

    return summary


def _top_score(matched: list[MatchedOffer]) -> int | None:
    scores = [item.match_score.total for item in matched if item.match_score is not None]
    return max(scores) if scores else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run synthetic end-to-end smoke test")
    parser.add_argument(
        "--output-dir",
        default="tmp/smoke",
        help="Directory for smoke output files",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run_smoke(Path(args.output_dir))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
