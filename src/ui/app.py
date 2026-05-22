"""Streamlit UI dla Recruitment Radar."""

# ruff: noqa: E402

from __future__ import annotations

import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

# Streamlit Cloud can execute this nested entrypoint with src/ui as import root.
# Ensure repository root is importable so `from src...` imports work reliably.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd
import streamlit as st

from src.config import settings
from src.export import export_to_excel, export_weekly_report
from src.matching.compare import JDParsed as MatchingJDParsed
from src.matching.pipeline import MatchedOffer, run_matching
from src.parser import JDParserError, parse_jd_sync
from src.parser.models import JDParsed as ParserJDParsed
from src.scrapers.base import ContractKind, JobOffer, SalaryPeriod, SalaryRange
from src.ui.helpers import (
    UnauthorizedError,
    list_keyword_profiles,
    load_latest_snapshot,
    parse_allowed_emails,
    require_authorized_email,
    snapshot_status,
    trigger_refresh,
)

APP_TITLE = "Recruitment Radar"
SCRAPING_PORTAL_OPTIONS = {
    "justjoin": "JustJoin",
    "nofluff": "NoFluffJobs",
    "rocketjobs": "RocketJobs",
    "pracuj": "Pracuj",
    "theprotocol": "TheProtocol",
}
DEFAULT_SCRAPING_PORTALS = ("justjoin", "nofluff", "rocketjobs", "pracuj")


def _get_streamlit_user() -> Any | None:
    return getattr(st, "user", None)


def _is_logged_in() -> bool:
    user = _get_streamlit_user()
    if user is None:
        return False
    return bool(getattr(user, "is_logged_in", False))


def _get_user_email() -> str | None:
    user = _get_streamlit_user()
    if user is None:
        return None

    email = getattr(user, "email", None)
    return email if isinstance(email, str) else None


def _render_login_gate(allowed_emails: tuple[str, ...]) -> None:
    if not allowed_emails:
        return

    if _is_logged_in():
        return

    st.title("📡 Recruitment Radar")
    st.info("Zaloguj się, aby uzyskać dostęp do aplikacji.")
    if st.button("Zaloguj przez SSO"):
        st.login()
    st.stop()


def _render_logout_control() -> None:
    if _is_logged_in():
        email = _get_user_email() or "authenticated user"
        st.sidebar.caption(f"Zalogowano jako: {email}")
        if st.sidebar.button("Wyloguj"):
            st.logout()


def _guard_auth() -> None:
    allowed_emails = parse_allowed_emails(settings.OAUTH_ALLOWED_EMAILS)
    _render_login_gate(allowed_emails)

    try:
        require_authorized_email(_get_user_email(), allowed_emails)
    except UnauthorizedError:
        st.error("Brak dostępu do aplikacji Recruitment Radar.")
        if _is_logged_in() and st.button("Wyloguj"):
            st.logout()
        st.stop()


@st.cache_data(ttl=600)
def _load_snapshot_cached() -> pd.DataFrame:
    return load_latest_snapshot()


def _snapshot_status_caption() -> str:
    info = snapshot_status()
    if info.snapshot_date is None:
        return "Brak snapshotów danych."
    return (
        f"Ostatnie dane: {info.snapshot_date}, liczba ofert: {info.offer_count}, "
        f"status: {info.status}"
    )


def _render_snapshot_health() -> None:
    info = snapshot_status()
    if info.snapshot_date is None:
        return

    if info.status == "failed":
        st.sidebar.error("Ostatni scraping nie zebrał danych.")
    elif info.status == "degraded":
        failed = ", ".join(info.failed_portals) or "nieznane portale"
        st.sidebar.warning(f"Dane częściowe. Błędy: {failed}.")
    elif info.status == "success":
        st.sidebar.success("Ostatni scraping zakończył się sukcesem.")

    if info.portal_counts:
        st.sidebar.caption(
            "Oferty per portal: "
            + ", ".join(
                f"{portal}: {count}" for portal, count in sorted(info.portal_counts.items())
            )
        )

    if info.keyword_metrics:
        top_keywords = sorted(
            info.keyword_metrics.items(),
            key=lambda item: int(item[1].get("added_count") or 0),
            reverse=True,
        )[:5]
        st.sidebar.caption(
            "Top keywordy: "
            + ", ".join(
                f"{keyword}: {int(metric.get('added_count') or 0)}"
                for keyword, metric in top_keywords
            )
        )


def _salary_from_row(row: pd.Series) -> SalaryRange | None:
    try:
        salary_min = row.get("salary_min")
        salary_max = row.get("salary_max")
        currency = row.get("currency") or "PLN"

        period_raw = str(row.get("period") or "month").lower()
        period: SalaryPeriod = "hour" if period_raw == "hour" else "month"

        contract_raw = str(row.get("contract") or "b2b").lower()
        contract: ContractKind = "uop" if contract_raw == "uop" else "b2b"

        if pd.isna(salary_min) or pd.isna(salary_max):
            return None

        return SalaryRange(
            min=int(salary_min),
            max=int(salary_max),
            currency=str(currency),
            period=period,
            contract=contract,
        )
    except (TypeError, ValueError):
        return None


def _job_offer_from_row(row: pd.Series) -> JobOffer:
    published_raw = row.get("published_at")
    scraped_raw = row.get("scraped_at")

    published_at = _coerce_datetime(published_raw)
    scraped_at = _coerce_datetime(scraped_raw)

    tech_raw = row.get("tech_stack")
    if isinstance(tech_raw, str):
        tech_stack = tuple(item.strip() for item in tech_raw.split(",") if item.strip())
    elif isinstance(tech_raw, list | tuple):
        tech_stack = tuple(str(item) for item in tech_raw)
    else:
        tech_stack = ()

    return JobOffer(
        title=str(row.get("title") or ""),
        company=str(row.get("company") or ""),
        portal=str(row.get("portal") or ""),
        url=str(row.get("url") or ""),
        location=_optional_str(row.get("location")),
        work_mode=_optional_str(row.get("work_mode")),  # type: ignore[arg-type]
        seniority=_optional_str(row.get("seniority")),  # type: ignore[arg-type]
        tech_stack=tech_stack,
        salary=_salary_from_row(row),
        published_at=published_at,
        scraped_at=scraped_at,
        raw={str(key): value for key, value in row.to_dict().items()},
    )


def _optional_str(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = pd.to_datetime(value, utc=True)
        return cast(datetime, parsed.to_pydatetime())
    except Exception:
        return datetime.now(UTC)


def _offers_from_dataframe(df: pd.DataFrame) -> list[JobOffer]:
    if df.empty:
        return []
    return [_job_offer_from_row(row) for _, row in df.iterrows()]


def _matching_jd_from_parser(parsed: ParserJDParsed) -> MatchingJDParsed:
    salary = None
    if parsed.salary is not None:
        salary = SalaryRange(
            min=parsed.salary.min,
            max=parsed.salary.max,
            currency=parsed.salary.currency,
            period=parsed.salary.period,
            contract=parsed.salary.contract,
        )

    return MatchingJDParsed(
        title=parsed.title,
        company=None,
        location=parsed.location,
        work_mode=parsed.work_mode,
        seniority=parsed.seniority,
        tech_stack=tuple(parsed.tech_stack),
        salary=salary,
    )


def _matched_to_dataframe(matched: list[MatchedOffer]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for item in matched:
        offer = item.deduped.primary
        score = item.match_score.total if item.match_score else None
        salary = offer.salary
        rows.append(
            {
                "score": score,
                "title": offer.title,
                "company": offer.company,
                "portal": offer.portal,
                "location": offer.location,
                "work_mode": offer.work_mode,
                "seniority": offer.seniority,
                "salary_min": salary.min if salary else None,
                "salary_max": salary.max if salary else None,
                "currency": salary.currency if salary else None,
                "contract": salary.contract if salary else None,
                "url": offer.url,
                "tech_stack": ", ".join(offer.tech_stack),
            }
        )
    return pd.DataFrame(rows)


def _download_exports(matched: list[MatchedOffer], jd: MatchingJDParsed | None) -> None:
    if not matched:
        return

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        excel_path = export_to_excel(matched, jd, tmp_path / "recruitment_radar.xlsx")
        docx_path = export_weekly_report(
            matched,
            jd,
            datetime.now(UTC).strftime("%G-W%V"),
            tmp_path / "recruitment_radar_report.docx",
        )

        st.download_button(
            "📊 Pobierz Excel",
            data=excel_path.read_bytes(),
            file_name="recruitment_radar.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        st.download_button(
            "📄 Pobierz raport DOCX",
            data=docx_path.read_bytes(),
            file_name="recruitment_radar_report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )


def _render_sidebar() -> dict[str, Any]:
    _render_logout_control()
    st.sidebar.header("Filtry")

    selected_portals = st.sidebar.multiselect(
        "Portale",
        ["justjoin.it", "nofluffjobs.com", "rocketjobs.pl", "theprotocol.it", "pracuj.pl"],
        default=["justjoin.it", "nofluffjobs.com", "rocketjobs.pl", "theprotocol.it", "pracuj.pl"],
    )
    min_score = st.sidebar.slider("Minimalny match score", 0, 100, 0)
    dedup_threshold = st.sidebar.slider("Dedup threshold", 50, 100, 85)

    st.sidebar.header("Dane")
    st.sidebar.caption(_snapshot_status_caption())
    _render_snapshot_health()

    with st.sidebar.expander("Odśwież dane", expanded=False):
        keyword_profiles = list_keyword_profiles()
        profile_index = (
            keyword_profiles.index("consulting") if "consulting" in keyword_profiles else 0
        )
        keyword_profile = st.selectbox(
            "Profil keywordów",
            keyword_profiles,
            index=profile_index,
        )
        manual_keywords = st.text_input(
            "Ręczne keywordy",
            value="",
            placeholder="np. PMO Specialist,SAP",
        )
        scraping_portals = st.multiselect(
            "Portale do scrapingu",
            list(SCRAPING_PORTAL_OPTIONS),
            default=list(DEFAULT_SCRAPING_PORTALS),
            format_func=lambda key: SCRAPING_PORTAL_OPTIONS.get(key, key),
        )
        limit_per_portal = int(
            st.number_input(
                "Limit ofert per portal",
                min_value=1,
                max_value=5000,
                value=200,
                step=50,
            )
        )
        limit_per_keyword = int(
            st.number_input(
                "Limit ofert per keyword",
                min_value=1,
                max_value=500,
                value=50,
                step=10,
            )
        )

        if st.button("🔄 Odśwież teraz"):
            if not scraping_portals:
                st.error("Wybierz co najmniej jeden portal.")
            else:
                portals_arg = (
                    "all"
                    if tuple(scraping_portals) == DEFAULT_SCRAPING_PORTALS
                    else ",".join(scraping_portals)
                )
                workflow_inputs = {
                    "keywords": manual_keywords.strip(),
                    "keyword_profile": str(keyword_profile),
                    "portals": portals_arg,
                    "limit_per_portal": str(limit_per_portal),
                    "limit_per_keyword": str(limit_per_keyword),
                }
                try:
                    workflow_id = trigger_refresh(
                        repo_full_name=settings.GITHUB_REPO_FULL_NAME,
                        inputs=workflow_inputs,
                    )
                    st.sidebar.success(f"Uruchomiono workflow: {workflow_id}")
                except Exception as exc:
                    st.sidebar.error(f"Nie udało się uruchomić workflow: {exc}")

    return {
        "selected_portals": selected_portals,
        "min_score": min_score,
        "dedup_threshold": dedup_threshold,
    }


def _render_compare_tab(filters: dict[str, Any]) -> None:
    st.subheader("Porównaj z naszą ofertą")

    jd_text = st.text_area("Wklej Job Description", height=300)

    if st.button("Parsuj JD"):
        if not jd_text.strip():
            st.warning("Wklej treść ogłoszenia.")
        else:
            try:
                parsed = parse_jd_sync(jd_text)
                st.session_state["parsed_jd"] = parsed
                st.success("JD sparsowane.")
            except JDParserError as exc:
                st.error(f"Błąd parsera JD: {exc}")

    parsed_jd = st.session_state.get("parsed_jd")
    if isinstance(parsed_jd, ParserJDParsed):
        st.markdown("### Sparsowana oferta")
        st.json(parsed_jd.model_dump())

        if st.button("Znajdź podobne oferty"):
            df = _load_snapshot_cached()
            if df.empty:
                st.warning("Brak snapshotów do porównania.")
                return

            if filters["selected_portals"] and "portal" in df.columns:
                df = df[df["portal"].isin(filters["selected_portals"])]

            offers = _offers_from_dataframe(df)
            matching_jd = _matching_jd_from_parser(parsed_jd)
            matched = run_matching(
                offers,
                our_offer=matching_jd,
                dedup_threshold=filters["dedup_threshold"],
                min_match_score=filters["min_score"],
            )
            st.session_state["matched_offers"] = matched
            st.session_state["matching_jd"] = matching_jd

    matched = st.session_state.get("matched_offers", [])
    stored_matching_jd = st.session_state.get("matching_jd")

    if isinstance(matched, list) and matched:
        table = _matched_to_dataframe(matched)
        st.dataframe(
            table,
            use_container_width=True,
            column_config={"url": st.column_config.LinkColumn("Link")},
        )
        _download_exports(
            matched,
            stored_matching_jd if isinstance(stored_matching_jd, MatchingJDParsed) else None,
        )


def _render_browse_tab(filters: dict[str, Any]) -> None:
    st.subheader("Przegląd ogłoszeń")

    df = _load_snapshot_cached()
    if df.empty:
        st.info("Brak snapshotów w data/snapshots.")
        return

    if filters["selected_portals"] and "portal" in df.columns:
        df = df[df["portal"].isin(filters["selected_portals"])]

    st.metric("Liczba ofert", len(df))
    st.dataframe(df, use_container_width=True)


def _render_history_tab() -> None:
    st.subheader("Historia snapshotów")

    base_dir = Path("data/snapshots")
    if not base_dir.exists():
        st.info("Brak katalogu data/snapshots.")
        return

    snapshots = sorted(path.name for path in base_dir.iterdir() if path.is_dir())
    if not snapshots:
        st.info("Brak snapshotów.")
        return

    st.write("Dostępne snapshoty:")
    st.write(snapshots)


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="📡", layout="wide")
    _guard_auth()

    st.title("📡 Recruitment Radar")
    st.caption(_snapshot_status_caption())

    filters = _render_sidebar()

    tab_compare, tab_browse, tab_history = st.tabs(
        ["Porównaj z naszą ofertą", "Przegląd ogłoszeń", "Historia"]
    )

    with tab_compare:
        _render_compare_tab(filters)
    with tab_browse:
        _render_browse_tab(filters)
    with tab_history:
        _render_history_tab()


if __name__ == "__main__":
    main()
