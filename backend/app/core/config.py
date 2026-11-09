
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    app_name: str = "RepoPilot AI"
    app_env: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    database_url: str

    # Gemini configuration
    gemini_api_key: str = ""
    embedding_model: str = "gemini-embedding-001"
    embedding_batch_size: int = 16

    # LLM Configuration
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.5-flash"


    # GitHub configuration
    github_token: str = ""

    # Qdrant configuration
    qdrant_path: str = str(
        Path(__file__).resolve().parents[2] / "qdrant_data"
    )
    qdrant_collection: str = "repo_chunks"

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
