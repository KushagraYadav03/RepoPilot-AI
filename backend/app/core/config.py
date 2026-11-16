
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):

    app_name: str = "RepoPilot AI"
    app_env: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    database_url: str

    # Gemini configuration
    # Gemini is still used by the LLM provider.
    gemini_api_key: str = ""

    # Local FastEmbed configuration
    embedding_model: str = "jinaai/jina-embeddings-v2-base-code"
    embedding_batch_size: int = 16
    embedding_dimension: int = 768

    embedding_cache_dir: str = str(
        BACKEND_DIR / "fastembed_cache"
    )

    embedding_threads: int = 4

    # LLM configuration
    llm_provider: str = "gemini"
    llm_model: str = "gemini-3.5-flash-lite"

    # GitHub configuration
    github_token: str = ""

    # Qdrant local persistent storage
    qdrant_path: str = str(
        BACKEND_DIR / "qdrant_data"
    )

    # New collection for Jina 768-dimensional vectors.
    # Existing repo_chunks collection remains untouched.
    qdrant_collection: str = "repo_chunks_jina"

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
