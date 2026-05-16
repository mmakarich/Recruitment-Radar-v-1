"""Verify Streamlit Cloud deployment readiness.

This script does not call Streamlit Cloud APIs.
It checks repository-side deployment prerequisites:

- Streamlit app entrypoint exists
- Streamlit config exists
- secrets example exists
- real secrets.toml is not required and should remain local-only
- deployment docs exist
- GitHub Actions scraping workflow exists
- UI contains native Streamlit login/logout references
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_FILES = (
    "src/ui/app.py",
    ".streamlit/config.toml",
    ".streamlit/secrets.example.toml",
    "docs/STREAMLIT_CLOUD_DEPLOYMENT.md",
    "docs/RELEASE_CHECKLIST.md",
    ".github/workflows/scrape-weekly.yml",
)

REQUIRED_APP_SNIPPETS = (
    "st.login",
    "st.logout",
    "OAUTH_ALLOWED_EMAILS",
)

REQUIRED_APP_ALTERNATIVES = {
    "st.user access": ("st.user", 'getattr(st, "user"', "getattr(st, 'user'"),
}

REQUIRED_DOC_SNIPPETS = (
    "src/ui/app.py",
    "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN",
    "OAUTH_ALLOWED_EMAILS",
)


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def run_checks(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    for relative_path in REQUIRED_FILES:
        path = root / relative_path
        if not path.exists():
            errors.append(f"Missing required file: {relative_path}")

    secrets_file = root / ".streamlit/secrets.toml"
    if secrets_file.exists():
        warnings.append(
            "Local .streamlit/secrets.toml exists. This is OK locally, "
            "but it must not be committed."
        )

    gitignore = _read_text(root / ".gitignore")
    if ".streamlit/secrets.toml" not in gitignore:
        errors.append(".gitignore should include .streamlit/secrets.toml")

    app_text = _read_text(root / "src/ui/app.py")
    for snippet in REQUIRED_APP_SNIPPETS:
        if snippet not in app_text:
            errors.append(f"src/ui/app.py does not contain expected snippet: {snippet}")

    for label, alternatives in REQUIRED_APP_ALTERNATIVES.items():
        if not any(alternative in app_text for alternative in alternatives):
            errors.append(f"src/ui/app.py does not contain expected snippet group: {label}")

    deployment_doc = _read_text(root / "docs/STREAMLIT_CLOUD_DEPLOYMENT.md")
    for snippet in REQUIRED_DOC_SNIPPETS:
        if snippet not in deployment_doc:
            errors.append(
                f"docs/STREAMLIT_CLOUD_DEPLOYMENT.md does not contain expected snippet: {snippet}"
            )

    workflow_text = _read_text(root / ".github/workflows/scrape-weekly.yml")
    if "workflow_dispatch" not in workflow_text:
        errors.append("scrape-weekly workflow should support workflow_dispatch")
    if "schedule:" not in workflow_text:
        errors.append("scrape-weekly workflow should support schedule")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "checked_files": list(REQUIRED_FILES),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify deployment readiness")
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_checks(Path(args.root))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
