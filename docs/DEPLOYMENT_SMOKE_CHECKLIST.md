# Deployment Smoke Checklist - Streamlit Cloud

## 1. Pre-deploy local readiness

Run:

    python scripts/verify_deployment_readiness.py
    python scripts/smoke_end_to_end.py --output-dir tmp/smoke
    python -m pytest tests/unit/ -q

Expected:

- readiness ok = true
- smoke generates XLSX and DOCX
- unit tests pass

## 2. Streamlit Cloud app settings

Repository:

    mmakarich/Recruitment-Radar-v-1

Branch:

    main

Main file path:

    src/ui/app.py

## 3. Secrets

Configure secrets in Streamlit Cloud app settings, not in repository:

    ANTHROPIC_API_KEY
    GITHUB_TOKEN
    OAUTH_ALLOWED_EMAILS

## 4. First deploy smoke

Check in browser:

- app loads
- login gate appears when allowlist is configured
- authorized email can access app
- sidebar renders
- snapshot empty state is handled
- JD text area renders
- no secrets are displayed

## 5. Workflow dispatch smoke

Run conservative GitHub Actions workflow:

    keywords = python
    portals = justjoin,nofluff
    limit_per_portal = 10

Check that summary.json is produced and app can read snapshot data after redeploy/reload.
