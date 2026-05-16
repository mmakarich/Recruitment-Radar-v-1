"""Helpery dla Streamlit UI.

Ten moduł jest celowo niezależny od Streamlit, żeby dało się go testować
jednostkowo bez uruchamiania aplikacji webowej.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import settings


@dataclass(frozen=True, slots=True)
class SnapshotInfo:
    snapshot_dir: Path | None
    snapshot_date: str | None
    offer_count: int


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

    df = load_latest_snapshot(base_dir)
    return SnapshotInfo(
        snapshot_dir=latest_dir,
        snapshot_date=latest_dir.name,
        offer_count=len(df),
    )


def trigger_refresh(
    repo_full_name: str = "mmakarich/Recruitment-Radar-v-1",
    workflow_file: str = "scrape-weekly.yml",
    ref: str = "main",
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
    workflow.create_dispatch(ref=ref)

    return f"{repo_full_name}/{workflow_file}@{ref}"
