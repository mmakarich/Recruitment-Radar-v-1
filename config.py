"""Konfiguracja aplikacji.

Settings są celowo lekkie — dociągamy z .env tylko to, co realnie używają
moduły. Pełna lista pól docelowo z Promptu 0; tu trzymamy minimum potrzebne
do działania scraperów (timeout, dedup threshold) plus zaślepki na sekrety,
żeby pydantic-settings nie wybuchał gdy są ustawione w .env.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ANTHROPIC_API_KEY: str = ""
    GITHUB_TOKEN: str = ""
    OAUTH_ALLOWED_EMAILS: str = ""
    # Wspólny timeout dla wszystkich scraperów — większość portali odpowiada w <5s,
    # 30s daje margines na wolniejsze API i Playwrighta.
    SCRAPER_TIMEOUT_S: float = 30.0
    DEDUP_THRESHOLD: int = 85


settings = Settings()
