"""
Application settings for Retrovue.

This module defines all configuration settings for Retrovue using Pydantic BaseSettings.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Main application settings using Pydantic BaseSettings."""

    # Database settings (keep existing)
    database_url: str = Field(
        default="postgresql+psycopg://retrovue:mb061792@192.168.1.50:5432/retrovue",
        alias="DATABASE_URL",
    )
    # NEW: optional test DB
    test_database_url: str | None = Field(default=None, alias="TEST_DATABASE_URL")
    echo_sql: bool = Field(default=False, alias="ECHO_SQL")
    pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    pool_timeout: int = Field(default=30, alias="DB_POOL_TIMEOUT")
    connect_timeout: int = Field(default=30, alias="DB_CONNECT_TIMEOUT")

    # New settings
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    media_roots: str = Field(default="", alias="MEDIA_ROOTS")  # Comma-separated paths
    plex_token: str = Field(default="", alias="PLEX_TOKEN")
    allowed_origins: str = Field(default="*", alias="ALLOWED_ORIGINS")  # Comma-separated origins
    env: str = Field(default="dev", alias="ENV")  # dev|prod|test

    model_config: SettingsConfigDict = SettingsConfigDict(
        env_file=".env", 
        case_sensitive=False,
        extra="ignore"  # Ignore extra fields like PYTHONPATH from .env
    )


def _resolve_env_file() -> str | None:
    # 1) Explicit override
    explicit = os.getenv("RETROVUE_ENV_FILE")
    if explicit and Path(explicit).is_file():
        return explicit

    # 2) CWD .env
    cwd_env = Path.cwd() / ".env"
    if cwd_env.is_file():
        return str(cwd_env)

    # 3) Walk up from this file to find nearest .env
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / ".env"
        if candidate.is_file():
            return str(candidate)
    return None


# Global settings instance (load from best-effort .env discovery)
_env_file = _resolve_env_file()
settings = Settings(_env_file=_env_file) if _env_file else Settings()  # type: ignore[call-arg]
