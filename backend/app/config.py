from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Application settings loaded from OTD_-prefixed environment variables."""

    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_prefix="OTD_",
        extra="ignore",
    )

    app_name: str = "OutTheDoor API"
    environment: str = "development"
    database_url: str = "sqlite:///./out_the_door.db"
    cors_origins: list[str] = ["http://localhost:5173"]

@lru_cache
def get_settings() -> Settings:
    return Settings()
