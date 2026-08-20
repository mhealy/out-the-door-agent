from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
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
    langgraph_checkpoint_path: Path = Path("./out_the_door_checkpoints.db")
    cors_origins: list[str] = ["http://localhost:5173"]
    quote_extraction_model: str = "gpt-5.6"
    followup_drafting_model: str = "gpt-5.6"
    openai_api_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
