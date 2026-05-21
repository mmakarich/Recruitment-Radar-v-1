from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.matching.dedup import DedupedOffer, deduplicate
from src.scrapers.base import JobOffer, SalaryRange


def _offer(
    *,
    title: str,
    company: str,
    portal: str = "justjoin.it",
    url: str = "https://example.com/job",
    salary: SalaryRange | None = None,
    published_at: datetime | None = None,
    location: str | None = "Warszawa",
    work_mode: str | None = "remote",
    seniority: str | None = "senior",
    tech_stack: tuple[str, ...] = ("Python", "FastAPI"),
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
        published_at=published_at or datetime(2026, 1, 1, tzinfo=UTC),
        scraped_at=datetime(2026, 1, 2, tzinfo=UTC),
        raw={"url": url},
    )


def _salary(min_value: int, max_value: int) -> SalaryRange:
    return SalaryRange(
        min=min_value,
        max=max_value,
        currency="PLN",
        period="month",
        contract="b2b",
    )


class TestDeduplicate:
    def test_identical_offer_two_portals(self) -> None:
        first = _offer(
            title="Senior Python Developer",
            company="Acme",
            portal="justjoin.it",
            url="https://justjoin.it/job/1",
        )
        second = _offer(
            title="Senior Python Developer",
            company="Acme",
            portal="nofluffjobs.com",
            url="https://nofluffjobs.com/job/1",
        )

        result = deduplicate([first, second], threshold=85)

        assert len(result) == 1
        assert isinstance(result[0], DedupedOffer)
        assert result[0].primary in {first, second}
        assert len(result[0].duplicates) == 1
        assert result[0].portals == ("justjoin.it", "nofluffjobs.com")
        assert result[0].match_confidence == 100

    def test_similar_titles_below_threshold_not_merged(self) -> None:
        first = _offer(title="Senior Python Developer", company="Acme")
        second = _offer(title="Junior JavaScript Specialist", company="Different")

        result = deduplicate([first, second], threshold=85)

        assert len(result) == 2
        assert all(len(item.duplicates) == 0 for item in result)

    def test_company_name_normalization(self) -> None:
        first = _offer(
            title="Senior Python Developer",
            company="Acme Sp. z o.o.",
            portal="justjoin.it",
        )
        second = _offer(
            title="Senior Python Developer",
            company="Acme",
            portal="rocketjobs.pl",
        )

        result = deduplicate([first, second], threshold=85)

        assert len(result) == 1
        assert result[0].portals == ("justjoin.it", "rocketjobs.pl")

    def test_singleton_offer(self) -> None:
        offer = _offer(title="Data Engineer", company="Solo Company")

        result = deduplicate([offer], threshold=85)

        assert len(result) == 1
        assert result[0].primary is offer
        assert result[0].duplicates == ()
        assert result[0].portals == ("justjoin.it",)
        assert result[0].match_confidence == 100

    def test_three_way_dedup(self) -> None:
        offers = [
            _offer(title="Senior Python Developer", company="Acme", portal="justjoin.it"),
            _offer(title="Senior Python Developer", company="Acme", portal="nofluffjobs.com"),
            _offer(title="Senior Python Developer", company="Acme", portal="theprotocol.it"),
        ]

        result = deduplicate(offers, threshold=85)

        assert len(result) == 1
        assert len(result[0].duplicates) == 2
        assert result[0].portals == ("justjoin.it", "nofluffjobs.com", "theprotocol.it")

    def test_primary_is_newest_then_highest_salary(self) -> None:
        old_high_salary = _offer(
            title="Senior Python Developer",
            company="Acme",
            portal="justjoin.it",
            salary=_salary(25000, 30000),
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        new_lower_salary = _offer(
            title="Senior Python Developer",
            company="Acme",
            portal="nofluffjobs.com",
            salary=_salary(20000, 25000),
            published_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=1),
        )

        result = deduplicate([old_high_salary, new_lower_salary], threshold=85)

        assert len(result) == 1
        assert result[0].primary is new_lower_salary

    def test_salary_variants_are_collected(self) -> None:
        first = _offer(
            title="Senior Python Developer",
            company="Acme",
            portal="justjoin.it",
            salary=_salary(20000, 25000),
        )
        second = _offer(
            title="Senior Python Developer",
            company="Acme",
            portal="nofluffjobs.com",
            salary=_salary(22000, 28000),
        )

        result = deduplicate([first, second], threshold=85)

        assert len(result) == 1
        assert result[0].salary_variants == (
            _salary(20000, 25000),
            _salary(22000, 28000),
        )

    def test_same_company_title_different_seniority_not_merged(self) -> None:
        first = _offer(
            title="Python Developer",
            company="Acme",
            seniority="junior",
        )
        second = _offer(
            title="Python Developer",
            company="Acme",
            seniority="senior",
        )

        result = deduplicate([first, second], threshold=85)

        assert len(result) == 2

    def test_same_company_title_different_onsite_locations_not_merged(self) -> None:
        first = _offer(
            title="Python Developer",
            company="Acme",
            location="Warszawa",
            work_mode="onsite",
        )
        second = _offer(
            title="Python Developer",
            company="Acme",
            location="Kraków",
            work_mode="onsite",
        )

        result = deduplicate([first, second], threshold=85)

        assert len(result) == 2

    def test_remote_multilocation_offer_can_still_merge(self) -> None:
        first = _offer(
            title="Python Developer",
            company="Acme",
            location="Warszawa, Kraków",
            work_mode="remote",
        )
        second = _offer(
            title="Python Developer",
            company="Acme Sp. z o.o.",
            location="Kraków",
            work_mode="remote",
        )

        result = deduplicate([first, second], threshold=85)

        assert len(result) == 1
