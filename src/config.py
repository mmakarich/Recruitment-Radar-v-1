from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ANTHROPIC_API_KEY: str
    GITHUB_TOKEN: str
    OAUTH_ALLOWED_EMAILS: list[str] = []
    SCRAPER_TIMEOUT_S: int = 30
    DEDUP_THRESHOLD: int = 85

    class Config:
        env_file = ".env"


settings = Settings()
