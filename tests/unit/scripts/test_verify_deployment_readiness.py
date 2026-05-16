from __future__ import annotations

from pathlib import Path

from scripts.verify_deployment_readiness import run_checks


def _write(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _prepare_ready_repo(root: Path) -> None:
    _write(
        root / "src/ui/app.py",
        "st.login()\nst.logout()\nst.user\nOAUTH_ALLOWED_EMAILS\n",
    )
    _write(root / ".streamlit/config.toml", "[server]\nheadless = true\n")
    _write(root / ".streamlit/secrets.example.toml", 'ANTHROPIC_API_KEY = "replace-me"\n')
    _write(
        root / "docs/STREAMLIT_CLOUD_DEPLOYMENT.md",
        "src/ui/app.py\nANTHROPIC_API_KEY\nGITHUB_TOKEN\nOAUTH_ALLOWED_EMAILS\n",
    )
    _write(root / "docs/RELEASE_CHECKLIST.md", "release\n")
    _write(
        root / ".github/workflows/scrape-weekly.yml",
        "on:\n  schedule:\n  workflow_dispatch:\n",
    )
    _write(root / ".gitignore", ".streamlit/secrets.toml\n")


def test_run_checks_ready_repo(tmp_path: Path) -> None:
    _prepare_ready_repo(tmp_path)

    result = run_checks(tmp_path)

    assert result["ok"] is True
    assert result["errors"] == []


def test_run_checks_missing_required_file(tmp_path: Path) -> None:
    _prepare_ready_repo(tmp_path)
    (tmp_path / "src/ui/app.py").unlink()

    result = run_checks(tmp_path)

    assert result["ok"] is False
    assert any("src/ui/app.py" in error for error in result["errors"])


def test_run_checks_warns_about_local_secrets(tmp_path: Path) -> None:
    _prepare_ready_repo(tmp_path)
    _write(tmp_path / ".streamlit/secrets.toml", 'SECRET = "local"\n')

    result = run_checks(tmp_path)

    assert result["ok"] is True
    assert result["warnings"]


def test_run_checks_requires_secrets_gitignore(tmp_path: Path) -> None:
    _prepare_ready_repo(tmp_path)
    _write(tmp_path / ".gitignore", "")

    result = run_checks(tmp_path)

    assert result["ok"] is False
    assert any(".streamlit/secrets.toml" in error for error in result["errors"])


def test_run_checks_requires_workflow_dispatch(tmp_path: Path) -> None:
    _prepare_ready_repo(tmp_path)
    _write(root := tmp_path / ".github/workflows/scrape-weekly.yml", "on:\n  schedule:\n")
    assert root.exists()

    result = run_checks(tmp_path)

    assert result["ok"] is False
    assert any("workflow_dispatch" in error for error in result["errors"])
