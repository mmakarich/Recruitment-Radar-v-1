from __future__ import annotations

from datetime import UTC, datetime

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
    tech_stack: tuple[str, ...] = ("Python", "FastAPI"),
    seniority: str | None = "senior",
    salary: SalaryRange | None = None,
) -> JobOffer:
    return JobOffer(
        title=title,
        company=company,
        portal=portal,
        url=url,
        location="Warszawa",
        work_mode="remote",
        seniority=seniority,  # type: ignore[arg-type]
        tech_stack=tech_stack,
        salary=salary,
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        scraped_at=datetime(2026, 1, 2, tzinfo=UTC),
        raw={"url": url},
    )


class TestRunMatching:
    def test_pipeline_with_dedup_and_score(self) -> None:
        offers = [
            _offer(
                title="Senior Python Developer",
                company="Acme",
                portal="justjoin.it",
                url="https://justjoin.it/job/1",
                salary=_salary(20000, 25000),
            ),
            _offer(
                title="Senior Python Developer",
                company="Acme Sp. z o.o.",
                portal="nofluffjobs.com",
                url="https://nofluffjobs.com/job/1",
                salary=_salary(22000, 28000),
            ),
            _offer(
                title="Junior Graphic Designer",
                company="Design House",
                portal="rocketjobs.pl",
                url="https://rocketjobs.pl/job/1",
                tech_stack=("Figma",),
                seniority="junior",
            ),
        ]
        our = JDParsed(
            title="Senior Python Developer",
            company="Acme",
            location="Warszawa",
            work_mode="remote",
            seniority="senior",
            tech_stack=("Python", "FastAPI"),
            salary=_salary(18000, 24000),
        )

        result = run_matching(offers, our_offer=our, dedup_threshold=85)

        assert len(result) == 2
        assert all(isinstance(item, MatchedOffer) for item in result)
        assert result[0].match_score is not None
        assert result[1].match_score is not None
        assert result[0].match_score.total >= result[1].match_score.total
        assert len(result[0].deduped.portals) == 2

    def test_pipeline_filters_below_min_score(self) -> None:
        offers = [
            _offer(
                title="Senior Python Developer",
                company="Acme",
                portal="justjoin.it",
                url="https://justjoin.it/job/1",
            ),
            _offer(
                title="Junior Graphic Designer",
                company="Design House",
                portal="rocketjobs.pl",
                url="https://rocketjobs.pl/job/1",
                tech_stack=("Figma",),
                seniority="junior",
            ),
        ]
        our = JDParsed(
            title="Senior Python Developer",
            company="Acme",
            location="Warszawa",
            work_mode="remote",
            seniority="senior",
            tech_stack=("Python", "FastAPI"),
            salary=None,
        )

        result = run_matching(
            offers,
            our_offer=our,
            dedup_threshold=85,
            min_match_score=80,
        )

        assert len(result) == 1
        assert result[0].deduped.primary.company == "Acme"
        assert result[0].match_score is not None
        assert result[0].match_score.total >= 80

    def test_pipeline_can_require_tech_overlap(self) -> None:
        offers = [
            _offer(
                title="Senior Python Developer",
                company="Acme",
                portal="justjoin.it",
                url="https://justjoin.it/job/1",
                tech_stack=("Python",),
            ),
            _offer(
                title="Senior Java Developer",
                company="Backend House",
                portal="justjoin.it",
                url="https://justjoin.it/job/2",
                tech_stack=("Java", "Spring"),
            ),
        ]
        our = JDParsed(
            title="Senior Java Developer",
            seniority="senior",
            tech_stack=("Java",),
        )

        result = run_matching(offers, our_offer=our, require_tech_overlap=True)

        assert len(result) == 1
        assert result[0].deduped.primary.title == "Senior Java Developer"

    def test_pipeline_without_our_offer_returns_dedup_only(self) -> None:
        offers = [
            _offer(
                title="Senior Python Developer",
                company="Acme",
                portal="justjoin.it",
                url="https://justjoin.it/job/1",
            ),
            _offer(
                title="Senior Python Developer",
                company="Acme",
                portal="nofluffjobs.com",
                url="https://nofluffjobs.com/job/1",
            ),
        ]

        result = run_matching(offers, our_offer=None, dedup_threshold=85)

        assert len(result) == 1
        assert result[0].match_score is None
        assert result[0].deduped.portals == ("justjoin.it", "nofluffjobs.com")

    def test_pipeline_empty_input(self) -> None:
        assert run_matching([]) == []
