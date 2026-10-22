"""Application configuration and settings loaded from environment or .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore"
    )

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
    gemini_timeout_ms: int = 120_000
    gemini_max_retries: int = 5
    gemini_retry_min_wait_seconds: float = 3.0
    gemini_retry_max_wait_seconds: float = 20.0

    # Optional search provider keys
    semantic_scholar_api_key: str | None = None
    tavily_api_key: str | None = None
    ncbi_api_key: str | None = None

    # Database: lightweight SQLite by default (no external PostgreSQL container needed)
    database_url: str = "sqlite+aiosqlite:///./research.db"

    # App & CORS
    app_env: str = "development"
    log_level: str = "INFO"
    backend_cors_origins: str = "http://localhost:5173"

    # Search and pipeline limits
    max_queries_per_run: int = 12
    max_results_per_query: int = 10
    max_total_sources: int = 30
    http_timeout_seconds: int = 20
    provider_retry_count: int = 2
    max_validation_repair_attempts: int = 2
    planning_query_temperature: float | None = None

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
