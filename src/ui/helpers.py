"""Helpery dla Streamlit UI.

Ten moduł jest celowo niezależny od Streamlit, żeby dało się go testować
jednostkowo bez uruchamiania aplikacji webowej.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import settings


@dataclass(frozen=True, slots=True)
class SnapshotInfo:
    snapshot_dir: Path | None
    snapshot_date: str | None
    offer_count: int
    status: str = "unknown"
    portal_counts: dict[str, int] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    failed_portals: tuple[str, ...] = ()
    empty_portals: tuple[str, ...] = ()
    keyword_metrics: dict[str, dict[str, Any]] = field(default_factory=dict)


class UnauthorizedError(Exception):
    """Użytkownik nie znajduje się na liście dozwolonych adresów."""


def parse_allowed_emails(value: list[str] | tuple[str, ...] | str | None) -> tuple[str, ...]:
    """Normalizuje listę dozwolonych e-maili z env/Streamlit secrets."""
    if value is None:
        return ()

    raw_items = value.split(",") if isinstance(value, str) else list(value)

    normalized: list[str] = []
    seen: set[str] = set()

    for item in raw_items:
        cleaned = item.strip().lower()
        if cleaned and cleaned not in seen:
            normalized.append(cleaned)
            seen.add(cleaned)

    return tuple(normalized)


def is_authorized_email(email: str | None, allowed_emails: tuple[str, ...]) -> bool:
    """Sprawdza dostęp. Pusta lista allowed oznacza tryb lokalny bez blokady."""
    if not allowed_emails:
        return True

    if email is None:
        return False

    return email.strip().lower() in allowed_emails


def require_authorized_email(email: str | None, allowed_emails: tuple[str, ...]) -> None:
    if not is_authorized_email(email, allowed_emails):
        raise UnauthorizedError("Unauthorized email")


def find_latest_snapshot_dir(base_dir: Path = Path("data/snapshots")) -> Path | None:
    if not base_dir.exists():
        return None

    candidates = [path for path in base_dir.iterdir() if path.is_dir()]
    if not candidates:
        return None

    return sorted(candidates, key=lambda path: path.name)[-1]


def load_latest_snapshot(base_dir: Path = Path("data/snapshots")) -> pd.DataFrame:
    latest_dir = find_latest_snapshot_dir(base_dir)
    if latest_dir is None:
        return pd.DataFrame()

    parquet_files = sorted(latest_dir.glob("*.parquet"))
    if not parquet_files:
        return pd.DataFrame()

    frames = [pd.read_parquet(path) for path in parquet_files]
    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def snapshot_status(base_dir: Path = Path("data/snapshots")) -> SnapshotInfo:
    latest_dir = find_latest_snapshot_dir(base_dir)
    if latest_dir is None:
        return SnapshotInfo(snapshot_dir=None, snapshot_date=None, offer_count=0)

    summary = _load_summary(latest_dir)
    if summary:
        portal_counts = _portal_counts(summary)
        errors = _summary_errors(summary)
        return SnapshotInfo(
            snapshot_dir=latest_dir,
            snapshot_date=str(summary.get("snapshot_date") or latest_dir.name),
            offer_count=int(summary.get("total_count") or sum(portal_counts.values())),
            status=_summary_status(summary),
            portal_counts=portal_counts,
            errors=errors,
            failed_portals=tuple(str(portal) for portal in summary.get("failed_portals", errors)),
            empty_portals=tuple(str(portal) for portal in summary.get("empty_portals", ())),
            keyword_metrics=_keyword_metrics(summary),
        )

    df = load_latest_snapshot(base_dir)
    return SnapshotInfo(
        snapshot_dir=latest_dir,
        snapshot_date=latest_dir.name,
        offer_count=len(df),
        status="unknown",
    )


def _load_summary(snapshot_dir: Path) -> dict[str, Any]:
    summary_path = snapshot_dir / "summary.json"
    if not summary_path.exists():
        return {}

    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}


def _portal_counts(summary: dict[str, Any]) -> dict[str, int]:
    portals = summary.get("portals", {})
    if not isinstance(portals, dict):
        return {}

    counts: dict[str, int] = {}
    for portal, info in portals.items():
        if isinstance(info, dict):
            counts[str(portal)] = int(info.get("count") or 0)
    return counts


def _summary_errors(summary: dict[str, Any]) -> dict[str, str]:
    errors = summary.get("errors", {})
    if not isinstance(errors, dict):
        return {}
    return {str(portal): str(error) for portal, error in errors.items()}


def _keyword_metrics(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_metrics = summary.get("keyword_metrics", {})
    if not isinstance(raw_metrics, dict):
        return {}

    metrics: dict[str, dict[str, Any]] = {}
    for keyword, info in raw_metrics.items():
        if not isinstance(info, dict):
            continue
        metrics[str(keyword)] = {
            "fetched_count": int(info.get("fetched_count") or 0),
            "matched_count": int(info.get("matched_count") or 0),
            "added_count": int(info.get("added_count") or 0),
            "filtered_count": int(info.get("filtered_count") or 0),
            "duplicate_count": int(info.get("duplicate_count") or 0),
            "errors": info.get("errors") if isinstance(info.get("errors"), dict) else {},
        }
    return metrics


def _summary_status(summary: dict[str, Any]) -> str:
    status = summary.get("status")
    if isinstance(status, str) and status:
        return status

    errors = _summary_errors(summary)
    total_count = int(summary.get("total_count") or 0)
    if errors and total_count == 0:
        return "failed"
    if errors:
        return "degraded"
    return "success"


def list_keyword_profiles(
    config_path: Path = Path("config/scraping_keywords.toml"),
) -> tuple[str, ...]:
    if not config_path.exists():
        return ("consulting",)

    try:
        with config_path.open("rb") as file:
            payload = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError):
        return ("consulting",)

    profiles = payload.get("profiles")
    if not isinstance(profiles, dict):
        return ("consulting",)

    names = tuple(str(name) for name in profiles if isinstance(name, str))
    return names or ("consulting",)


def trigger_refresh(
    repo_full_name: str = "mmakarich/Recruitment-Radar-v-1",
    workflow_file: str = "scrape-weekly.yml",
    ref: str = "main",
    inputs: Mapping[str, str] | None = None,
    github_client: Any | None = None,
) -> str:
    """Uruchamia workflow_dispatch w GitHub Actions.

    github_client jest wstrzykiwany w testach. W aplikacji realnej tworzymy
    klienta PyGithub z settings.GITHUB_TOKEN.
    """
    client = github_client
    if client is None:
        if not settings.GITHUB_TOKEN:
            raise RuntimeError("GITHUB_TOKEN is not configured")
        from github import Github

        client = Github(settings.GITHUB_TOKEN)

    repo = client.get_repo(repo_full_name)
    workflow = repo.get_workflow(workflow_file)
    workflow.create_dispatch(ref=ref, inputs=dict(inputs or {}))

    return f"{repo_full_name}/{workflow_file}@{ref}"
