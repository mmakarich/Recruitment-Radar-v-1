# Deployment - Streamlit Community Cloud + OAuth

## Cel
Ten dokument opisuje deployment aplikacji Recruitment Radar na Streamlit Community Cloud.

Entry point aplikacji:

    src/ui/app.py

## Wymagania

- Repo GitHub z aktualnym main
- Konto Streamlit Community Cloud
- Dostep do ustawien aplikacji Streamlit
- Sekrety: ANTHROPIC_API_KEY, GITHUB_TOKEN, OAUTH_ALLOWED_EMAILS

## Deploy w Streamlit Community Cloud

1. Wejdz na Streamlit Community Cloud.
2. Polacz konto GitHub.
3. Wybierz repozytorium: mmakarich/Recruitment-Radar-v-1
4. Ustaw branch: main
5. Ustaw main file path: src/ui/app.py
6. W Advanced settings dodaj sekrety.

## Secrets

Nie commituj .streamlit/secrets.toml.
Uzywaj Streamlit Cloud -> App settings -> Secrets.

Przykladowa konfiguracja:

    ANTHROPIC_API_KEY = ...
    GITHUB_TOKEN = ...
    OAUTH_ALLOWED_EMAILS = [michal@example.com]

## OAuth / OIDC

Aplikacja uzywa natywnego Streamlit auth flow:

- st.login()
- st.logout()
- st.user.email
- st.user.is_logged_in

Jesli OAUTH_ALLOWED_EMAILS jest puste, aplikacja dziala lokalnie bez blokady.
Jesli OAUTH_ALLOWED_EMAILS zawiera adresy, aplikacja wymaga logowania i sprawdza e-mail uzytkownika.

## GitHub Actions refresh

UI ma przycisk Odswiez teraz, ktory uruchamia workflow:

    .github/workflows/scrape-weekly.yml

Wymagany sekret: GITHUB_TOKEN
Token musi miec uprawnienia do uruchamiania workflow dispatch w repo.

## Snapshoty danych

Aplikacja czyta dane z:

    data/snapshots/{YYYY-MM-DD}/*.parquet

Jesli snapshotow nie ma, UI pokaze komunikat o braku danych.

## Lokalny smoke test

    streamlit run src/ui/app.py

## Lokalna walidacja przed deployem

    python -m ruff check src tests scripts
    mypy src
    mypy scripts/run_scraping.py
    python -m pytest tests/unit/ -q

## Troubleshooting

### Brak dostepu

Sprawdz OAUTH_ALLOWED_EMAILS.

### Brak danych

Sprawdz czy istnieje katalog data/snapshots albo uruchom workflow Weekly scraping.

### Parser JD nie dziala

Sprawdz ANTHROPIC_API_KEY.

### Przycisk refresh nie dziala

Sprawdz GITHUB_TOKEN.
