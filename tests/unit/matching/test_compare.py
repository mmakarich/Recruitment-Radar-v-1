from __future__ import annotations

from datetime import UTC, datetime

from src.matching.compare import JDParsed, MatchScore, score_match
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
    title: str = "Senior Python Developer",
    company: str = "Acme",
    tech_stack: tuple[str, ...] = ("Python", "FastAPI", "AWS"),
    seniority: str | None = "senior",
    location: str | None = "Warszawa",
    work_mode: str | None = "remote",
    salary: SalaryRange | None = None,
) -> JobOffer:
    return JobOffer(
        title=title,
        company=company,
        portal="justjoin.it",
        url="https://example.com/job",
        location=location,
        work_mode=work_mode,  # type: ignore[arg-type]
        seniority=seniority,  # type: ignore[arg-type]
        tech_stack=tech_stack,
        salary=salary,
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        scraped_at=datetime(2026, 1, 2, tzinfo=UTC),
        raw={},
    )


class TestScoreMatch:
    def test_perfect_match(self) -> None:
        our = JDParsed(
            title="Senior Python Developer",
            company="Acme",
            location="Warszawa",
            work_mode="remote",
            seniority="senior",
            tech_stack=("Python", "FastAPI", "AWS"),
            salary=_salary(20000, 25000),
        )
        theirs = _offer(salary=_salary(22000, 28000))

        result = score_match(our, theirs)

        assert isinstance(result, MatchScore)
        assert result.total >= 95
        assert result.title_score == 100
        assert result.company_score == 100
        assert result.salary_score >= 60
        assert result.tech_overlap == 1.0
        assert result.seniority_match is True
        assert result.location_match is True
        assert result.work_mode_match is True
        assert result.salary_delta == 2000

    def test_no_match(self) -> None:
        our = JDParsed(
            title="Senior Python Developer",
            company="Acme",
            location="Warszawa",
            work_mode="remote",
            seniority="senior",
            tech_stack=("Python", "FastAPI"),
            salary=_salary(20000, 25000),
        )
        theirs = _offer(
            title="Junior Graphic Designer",
            company="Different",
            tech_stack=("Figma", "Photoshop"),
            seniority="junior",
            location="Gdańsk",
            work_mode="onsite",
            salary=_salary(7000, 9000),
        )

        result = score_match(our, theirs)

        assert result.total < 30
        assert result.company_score == 0
        assert result.salary_score == 0
        assert result.tech_overlap == 0.0
        assert result.seniority_match is False
        assert result.location_match is False
        assert result.work_mode_match is False

    def test_partial_match(self) -> None:
        our = JDParsed(
            title="Python Backend Developer",
            company=None,
            location="Warszawa",
            work_mode="remote",
            seniority="senior",
            tech_stack=("Python", "Django", "PostgreSQL"),
            salary=None,
        )
        theirs = _offer(
            title="Python Developer",
            company="Other Company",
            tech_stack=("Python", "Django", "AWS"),
            seniority="mid",
            location="Warszawa, Mazowieckie",
            work_mode="remote",
            salary=None,
        )

        result = score_match(our, theirs)

        assert 40 <= result.total <= 90
        assert result.company_score == 0
        assert result.tech_overlap > 0
        assert result.seniority_match is False
        assert result.location_match is True
        assert result.work_mode_match is True
        assert result.salary_delta is None

    def test_tech_overlap_rewards_required_stack_coverage(self) -> None:
        our = JDParsed(
            title="Senior Node.js Developer",
            seniority="senior",
            tech_stack=("Node.js",),
        )
        theirs = _offer(
            title="Senior Node Developer",
            tech_stack=(
                "TypeScript",
                "NodeJS",
                "Nest.js",
                "AWS",
                "PostgreSQL",
                "Docker",
            ),
            seniority="senior",
        )

        result = score_match(our, theirs)

        assert result.tech_overlap == 1.0
        assert result.total >= 60

    def test_salary_delta_calculation(self) -> None:
        our = JDParsed(
            title="Senior Python Developer",
            salary=_salary(18000, 24000),
        )
        theirs = _offer(salary=_salary(22000, 28000))

        result = score_match(our, theirs)

        assert result.salary_delta == 4000

    def test_company_score_normalizes_legal_suffixes(self) -> None:
        our = JDParsed(
            title="Senior Python Developer",
            company="Acme Sp. z o.o.",
        )
        theirs = _offer(company="Acme")

        result = score_match(our, theirs)

        assert result.company_score == 100

    def test_salary_score_rewards_overlapping_ranges(self) -> None:
        our = JDParsed(
            title="Senior Python Developer",
            salary=_salary(20000, 26000),
        )
        theirs = _offer(salary=_salary(22000, 28000))

        result = score_match(our, theirs)

        assert result.salary_score > 0

    def test_salary_score_zero_for_disjoint_ranges(self) -> None:
        our = JDParsed(
            title="Senior Python Developer",
            salary=_salary(20000, 26000),
        )
        theirs = _offer(salary=_salary(10000, 14000))

        result = score_match(our, theirs)

        assert result.salary_score == 0

    def test_salary_none_when_either_missing(self) -> None:
        our = JDParsed(
            title="Senior Python Developer",
            salary=None,
        )
        theirs = _offer(salary=_salary(22000, 28000))

        result = score_match(our, theirs)

        assert result.salary_delta is None

    def test_salary_none_when_currency_or_period_differs(self) -> None:
        our = JDParsed(
            title="Senior Python Developer",
            salary=SalaryRange(
                min=100,
                max=150,
                currency="PLN",
                period="hour",
                contract="b2b",
            ),
        )
        theirs = _offer(salary=_salary(22000, 28000))

        result = score_match(our, theirs)

        assert result.salary_delta is None

    def test_empty_tech_stacks_do_not_get_bonus(self) -> None:
        our = JDParsed(
            title="Backend Developer",
            tech_stack=(),
        )
        theirs = _offer(
            title="Backend Developer",
            tech_stack=(),
        )

        result = score_match(our, theirs)

        assert result.tech_overlap == 0.0
