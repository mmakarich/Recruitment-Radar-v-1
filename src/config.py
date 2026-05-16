from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ANTHROPIC_API_KEY: str = ""
    GITHUB_TOKEN: str = ""
    OAUTH_ALLOWED_EMAILS: list[str] = []
    SCRAPER_TIMEOUT_S: int = 30
    DEDUP_THRESHOLD: int = 85

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
