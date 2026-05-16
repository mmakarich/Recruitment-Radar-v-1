from __future__ import annotations

from pathlib import Path

from src.scrapers import JobOffer, PracujScraper, SalaryRange
from src.scrapers.pracuj import extract_offers_from_html, parse_salary_string


class TestParseSalaryString:
    def test_parse_monthly_b2b_salary(self) -> None:
        salary = parse_salary_string("20 000 - 28 000 zł netto (+ VAT) / mies. B2B")

        assert salary == SalaryRange(
            min=20000,
            max=28000,
            currency="PLN",
            period="month",
            contract="b2b",
        )

    def test_parse_monthly_uop_salary(self) -> None:
        salary = parse_salary_string("12 000 - 16 000 PLN brutto / mies. umowa o pracę")

        assert salary == SalaryRange(
            min=12000,
            max=16000,
            currency="PLN",
            period="month",
            contract="uop",
        )

    def test_parse_hourly_b2b_salary(self) -> None:
        salary = parse_salary_string("120 - 150 PLN/h B2B")

        assert salary == SalaryRange(
            min=120,
            max=150,
            currency="PLN",
            period="hour",
            contract="b2b",
        )

    def test_parse_empty_salary_returns_none(self) -> None:
        assert parse_salary_string("") is None

    def test_parse_salary_without_range(self) -> None:
        salary = parse_salary_string("15 000 zł / mies.")

        assert salary == SalaryRange(
            min=15000,
            max=15000,
            currency="PLN",
            period="month",
            contract="uop",
        )


class TestExtractOffersFromHtml:
    def test_extract_offers_from_fixture_html(self) -> None:
        html = Path("tests/fixtures/pracuj_sample.html").read_text()

        offers = extract_offers_from_html(html)

        assert len(offers) == 2
        assert offers[0]["title"] == "Senior Python Developer"
        assert offers[0]["company"] == "Pracuj Software"
        assert offers[0]["location"] == "Warszawa"
        assert "Python" in offers[0]["tags"]
        assert offers[0]["url"].startswith("/praca/")


class TestNormalize:
    def test_normalize_full_offer(self) -> None:
        raw = {
            "title": "Senior Python Developer",
            "company": "Pracuj Software",
            "location": "Warszawa",
            "salary": "20 000 - 28 000 zł netto (+ VAT) / mies. B2B",
            "url": "/praca/senior-python-developer-warszawa,oferta,abc123",
            "tags": ["Python", "FastAPI", "AWS", "Praca zdalna", "Senior"],
            "publishedAt": "2026-05-13T10:00:00Z",
        }

        offer = PracujScraper().normalize(raw)

        assert isinstance(offer, JobOffer)
        assert offer.title == "Senior Python Developer"
        assert offer.company == "Pracuj Software"
        assert offer.portal == "pracuj.pl"
        assert (
            offer.url
            == "https://www.pracuj.pl/praca/senior-python-developer-warszawa,oferta,abc123"
        )
        assert offer.location == "Warszawa"
        assert offer.work_mode == "remote"
        assert offer.seniority == "senior"
        assert offer.tech_stack == ("Python", "FastAPI", "AWS")
        assert offer.salary == SalaryRange(
            min=20000,
            max=28000,
            currency="PLN",
            period="month",
            contract="b2b",
        )
        assert offer.published_at.year == 2026
        assert offer.raw is raw

    def test_normalize_remote_work_detection(self) -> None:
        raw = {
            "title": "Mid Backend Developer",
            "company": "Backend House",
            "location": "Kraków",
            "salary": "12 000 - 16 000 zł brutto / mies. umowa o pracę",
            "url": "https://www.pracuj.pl/praca/mid-backend-developer-krakow,oferta,def456",
            "tags": ["Python", "Django", "Praca hybrydowa", "Regular"],
            "publishedAt": None,
        }

        offer = PracujScraper().normalize(raw)

        assert offer.work_mode == "hybrid"
        assert offer.seniority == "mid"
        assert offer.tech_stack == ("Python", "Django")
        assert offer.salary is not None
        assert offer.salary.contract == "uop"

    def test_normalize_missing_optional_fields(self) -> None:
        raw = {
            "title": "Backend Developer",
            "company": "No Salary Company",
            "url": "/praca/backend-developer,oferta,ghi789",
            "tags": [],
        }

        offer = PracujScraper().normalize(raw)

        assert offer.location is None
        assert offer.work_mode is None
        assert offer.seniority is None
        assert offer.tech_stack == ()
        assert offer.salary is None
