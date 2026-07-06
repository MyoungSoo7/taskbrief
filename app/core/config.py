from functools import cached_property
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "sqlite+aiosqlite:///./taskbrief.db"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    llm_timeout_seconds: float = 10.0
    timezone: str = "Asia/Seoul"

    @cached_property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


settings = Settings()
