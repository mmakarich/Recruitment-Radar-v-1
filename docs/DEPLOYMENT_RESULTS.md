# Deployment Results - Recruitment Radar

## Prompt 14 - Real Streamlit Cloud deploy and live smoke

Date: 2026-05-16

## Streamlit Cloud

- App URL: https://recruitment-radar-v-1-2q8aw6vlpmsitvvqrcetr2.streamlit.app/
- Entry point: src/ui/app.py
- Branch: main
- Status: app started successfully
- UI status: UI sees snapshot data

## GitHub Actions smoke

- Workflow: Weekly scraping
- Run ID: 25972263046
- Trigger: workflow_dispatch
- Input keywords: python
- Input portals: nofluff
- Input limit_per_portal: 10
- Result: success

## Snapshot result

- Snapshot date: 2026-05-16
- Snapshot file: data/snapshots/2026-05-16/nofluff.parquet
- Summary file: data/snapshots/2026-05-16/summary.json
- Portal: nofluff
- Offers count: 10
- Errors: none

## Local validation after snapshot pull

- ruff: All checks passed
- mypy src: Success
- mypy scripts/run_scraping.py: Success
- mypy scripts/smoke_end_to_end.py: Success
- mypy scripts/verify_deployment_readiness.py: Success
- verify_deployment_readiness.py: ok true
- pytest tests/unit/ -q: 146 passed

## Known non-blocking warnings

- GitHub Actions displayed a Node.js 20 deprecation warning for actions/checkout@v4, actions/setup-python@v5 and actions/upload-artifact@v4.
- GitHub Actions displayed a non-blocking git exit code 128 annotation, but the workflow completed successfully and committed the snapshot.

## Result

Prompt 14 live deployment smoke is successful.
