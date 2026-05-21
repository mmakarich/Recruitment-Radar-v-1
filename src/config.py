from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"
    JD_PARSER_MAX_INPUT_CHARS: int = 8_000
    GITHUB_TOKEN: str = ""
    GITHUB_REPO_FULL_NAME: str = "mmakarich/Recruitment-Radar-v-1"
    OAUTH_ALLOWED_EMAILS: list[str] = []
    SCRAPER_TIMEOUT_S: int = 30
    DEDUP_THRESHOLD: int = 85

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
