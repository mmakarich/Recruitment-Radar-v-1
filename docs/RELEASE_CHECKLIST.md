# Release Checklist - Recruitment Radar

## 1. Local quality gate

Run before every release:

    python -m ruff check src tests scripts
    mypy src
    mypy scripts/run_scraping.py
    mypy scripts/smoke_end_to_end.py
    python -m pytest tests/unit/ -q
    python scripts/smoke_end_to_end.py --output-dir tmp/smoke

Expected:

- ruff: All checks passed
- mypy src: Success
- mypy scripts/run_scraping.py: Success
- mypy scripts/smoke_end_to_end.py: Success
- pytest: all unit tests passed
- smoke: Excel and DOCX generated

## 2. Git status

    git status --short

Expected: empty output.

## 3. Streamlit local smoke

    streamlit run src/ui/app.py

Check:

- app starts
- sidebar renders
- empty snapshot state is handled
- JD text area renders
- export buttons appear after matching data exists

## 4. GitHub Actions

Check workflows:

- Tests/lint-and-test
- Weekly scraping

Manual run:

    Actions -> Weekly scraping -> Run workflow

Use conservative values first:

    keywords = python
    portals = justjoin,nofluff
    limit_per_portal = 10

## 5. Streamlit Cloud

Deployment config:

    Branch: main
    Entry point: src/ui/app.py

Required secrets:

    ANTHROPIC_API_KEY
    GITHUB_TOKEN
    OAUTH_ALLOWED_EMAILS

## 6. Data snapshots

Expected structure:

    data/snapshots/{YYYY-MM-DD}/{portal}.parquet
    data/snapshots/{YYYY-MM-DD}/summary.json

## 7. Rollback

If a release breaks UI or scraping:

1. Revert the merge commit.
2. Push revert to main.
3. Confirm Streamlit Cloud redeploys.
4. Run quality gate again.

## 8. Known safe state

Latest known safe checkpoint after Prompt 11:

- ruff: OK
- mypy src: OK
- mypy scripts/run_scraping.py: OK
- pytest tests/unit/ -q: 136 passed
