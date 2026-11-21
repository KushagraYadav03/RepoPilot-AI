
from functools import lru_cache
from pathlib import Path

from pydantic import Field
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
    gemini_api_key: str = ""

    # FastEmbed configuration
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

    # Qdrant configuration
    qdrant_path: str = str(
        BACKEND_DIR / "qdrant_data"
    )

    qdrant_collection: str = "repo_chunks_jina"

    # Docker sandbox configuration

    sandbox_python_image: str = (
        "repopilot-python-sandbox:latest"
    )

    sandbox_java_image: str = (
        "repopilot-java-sandbox:latest"
    )

    sandbox_timeout_seconds: int = Field(
        default=10,
        ge=1,
        le=300,
    )

    sandbox_memory_limit: str = Field(
        default="256m",
        pattern=r"^[1-9][0-9]*[kKmMgG]?$",
    )

    sandbox_cpu_limit: float = Field(
        default=0.5,
        gt=0,
        le=8,
    )

    sandbox_pids_limit: int = Field(
        default=64,
        ge=1,
        le=4096,
    )

    sandbox_max_output_bytes: int = Field(
        default=65536,
        ge=1,
        le=10_485_760,
    )

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
