"""Application Configuration Module.

This file loads settings and environment variables (from the `.env` file or the OS).
It uses Pydantic Settings to automatically validate data types and provide safe defaults.
"""

from typing import List, Union

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for the BYKERS application."""

    # Environment name: 'dev', 'test', 'staging', or 'prod'
    ENV: str = "dev"

    # Async PostgreSQL connection string
    # Must use postgresql+asyncpg:// for SQLAlchemy async engine
    DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/gis_database"
    )

    # JWT signing key (Keep secret in production!)
    SECRET_KEY: str = "dev-insecure-secret-key-change-in-production-min-32-chars"

    # Token expiration periods
    ACCESS_TOKEN_MINUTES: int = 15
    REFRESH_TOKEN_DAYS: int = 30

    # OTP (One-Time Password) parameters
    OTP_EXPIRES_MINUTES: int = 5
    OTP_RESEND_SECONDS: int = 60
    OTP_MAX_ATTEMPTS: int = 5
    OTP_MAX_SENDS_PER_HOUR: int = 5

    # Dev OTP testing support
    # DEV_FIXED_OTP will only work if ENV == 'dev' AND the phone is in ALLOWED_TEST_PHONES
    DEV_FIXED_OTP: str = "123456"
    ALLOWED_TEST_PHONES: List[str] = [
        "+919876543210",
        "+919876543211",
        "+919876543212",
        "+919876543213",
        "+919876543214",
        "+919876543215",
    ]

    # CORS origins: In dev defaults to allow all, or a specific list of domains
    CORS_ORIGINS: List[str] = ["*"]

    @field_validator("ALLOWED_TEST_PHONES", mode="before")
    @classmethod
    def parse_test_phones(cls, v: Union[str, List[str]]) -> List[str]:
        """Convert comma-separated phone string to a list of clean phone numbers."""
        if isinstance(v, str):
            return [phone.strip() for phone in v.split(",") if phone.strip()]
        return v

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        """Convert comma-separated origin string to a list of allowed origins."""
        if isinstance(v, str):
            if v.strip() == "*":
                return ["*"]
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Global settings instance to import across the app
settings = Settings()
