from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.ui.helpers import (
    UnauthorizedError,
    find_latest_snapshot_dir,
    is_authorized_email,
    load_latest_snapshot,
    parse_allowed_emails,
    require_authorized_email,
    snapshot_status,
    trigger_refresh,
)


def test_parse_allowed_emails_from_string() -> None:
    result = parse_allowed_emails("A@EXAMPLE.com, b@example.com, a@example.com")

    assert result == ("a@example.com", "b@example.com")


def test_parse_allowed_emails_from_list() -> None:
    result = parse_allowed_emails([" User@One.com ", "admin@one.com"])

    assert result == ("user@one.com", "admin@one.com")


def test_auth_allows_when_allowed_list_empty() -> None:
    assert is_authorized_email(None, ()) is True


def test_auth_blocks_unauthorized_email() -> None:
    allowed = ("allowed@example.com",)

    assert is_authorized_email("blocked@example.com", allowed) is False
    with pytest.raises(UnauthorizedError):
        require_authorized_email("blocked@example.com", allowed)


def test_auth_allows_whitelisted_email() -> None:
    allowed = ("allowed@example.com",)

    assert is_authorized_email("ALLOWED@example.com", allowed) is True
    require_authorized_email("ALLOWED@example.com", allowed)


def test_find_latest_snapshot_dir_picks_newest(tmp_path: Path) -> None:
    base = tmp_path / "snapshots"
    (base / "2026-05-01").mkdir(parents=True)
    (base / "2026-05-15").mkdir(parents=True)

    latest = find_latest_snapshot_dir(base)

    assert latest == base / "2026-05-15"


def test_load_latest_snapshot_empty_dir(tmp_path: Path) -> None:
    base = tmp_path / "snapshots"
    base.mkdir()

    df = load_latest_snapshot(base)

    assert df.empty


def test_load_latest_snapshot_reads_parquet_files(tmp_path: Path) -> None:
    base = tmp_path / "snapshots"
    old_dir = base / "2026-05-01"
    new_dir = base / "2026-05-15"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)

    pd.DataFrame([{"title": "Old"}]).to_parquet(old_dir / "old.parquet")
    pd.DataFrame([{"title": "A"}, {"title": "B"}]).to_parquet(new_dir / "a.parquet")
    pd.DataFrame([{"title": "C"}]).to_parquet(new_dir / "b.parquet")

    df = load_latest_snapshot(base)

    assert len(df) == 3
    assert set(df["title"]) == {"A", "B", "C"}


def test_snapshot_status_empty(tmp_path: Path) -> None:
    status = snapshot_status(tmp_path / "missing")

    assert status.snapshot_dir is None
    assert status.snapshot_date is None
    assert status.offer_count == 0


def test_snapshot_status_counts_latest_snapshot(tmp_path: Path) -> None:
    base = tmp_path / "snapshots"
    new_dir = base / "2026-05-15"
    new_dir.mkdir(parents=True)

    pd.DataFrame([{"title": "A"}, {"title": "B"}]).to_parquet(new_dir / "offers.parquet")

    status = snapshot_status(base)

    assert status.snapshot_dir == new_dir
    assert status.snapshot_date == "2026-05-15"
    assert status.offer_count == 2


class _FakeWorkflow:
    def __init__(self) -> None:
        self.refs: list[str] = []

    def create_dispatch(self, ref: str) -> None:
        self.refs.append(ref)


class _FakeRepo:
    def __init__(self, workflow: _FakeWorkflow) -> None:
        self.workflow = workflow

    def get_workflow(self, workflow_file: str) -> _FakeWorkflow:
        assert workflow_file == "scrape-weekly.yml"
        return self.workflow


class _FakeGithub:
    def __init__(self, workflow: _FakeWorkflow) -> None:
        self.workflow = workflow
        self.requested_repos: list[str] = []

    def get_repo(self, repo_full_name: str) -> _FakeRepo:
        self.requested_repos.append(repo_full_name)
        return _FakeRepo(self.workflow)


def test_trigger_refresh_uses_injected_client() -> None:
    workflow = _FakeWorkflow()
    client = _FakeGithub(workflow)

    result = trigger_refresh(github_client=client)

    assert result == "mmakarich/Recruitment-Radar-v-1/scrape-weekly.yml@main"
    assert client.requested_repos == ["mmakarich/Recruitment-Radar-v-1"]
    assert workflow.refs == ["main"]
