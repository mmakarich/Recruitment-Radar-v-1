"""Konfiguracja aplikacji ładowana ze zmiennych środowiskowych.

Pojedyncze źródło prawdy dla wszystkich ustawień runtime. Wszystkie wartości
domyślne tutaj — żadnych magicznych liczb rozsianych po module.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Ustawienia aplikacji.

    Ładowane z .env (lokalnie) lub ze st.secrets / GitHub Secrets (produkcja).
    Pydantic waliduje typy i zgłasza błąd przy braku wymaganych pól.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Wymagane w produkcji, opcjonalne lokalnie (default puste żeby testy nie wymagały .env)
    ANTHROPIC_API_KEY: str = Field(default="", description="Klucz Claude API dla parsera JD")
    GITHUB_TOKEN: str = Field(default="", description="PAT z permission Actions:write")

    # Comma-separated lista emaili dopuszczonych do logowania w Streamlit
    OAUTH_ALLOWED_EMAILS: str = Field(default="")

    # Timeouts i progi — łatwo zmienić bez edycji kodu
    SCRAPER_TIMEOUT_S: int = Field(default=30, ge=5, le=120)
    DEDUP_THRESHOLD: int = Field(default=85, ge=50, le=100)

    @property
    def allowed_emails_list(self) -> list[str]:
        """OAUTH_ALLOWED_EMAILS jako lista (split + strip + lowercase)."""
        if not self.OAUTH_ALLOWED_EMAILS:
            return []
        return [e.strip().lower() for e in self.OAUTH_ALLOWED_EMAILS.split(",") if e.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings — cache żeby nie czytać .env wielokrotnie."""
    return Settings()


# Wygodny alias do importu w innych modułach
settings = get_settings()
