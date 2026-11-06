"""Application Configuration Module.

This file loads settings and environment variables (from the `.env` file or the OS).
It uses Pydantic Settings to automatically validate data types and provide safe defaults.
"""

from typing import List, Optional, Union

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for the BYKERS application."""

    # Environment name: 'dev', 'test', 'staging', or 'prod'
    ENV: str = "dev"

    # Async PostgreSQL connection string for development
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/bykers_dev"

    # Async PostgreSQL connection string for automated tests
    TEST_DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/bykers_test"

    # Storage provider: 'local' (dev/test) or 'azure' (staging/prod)
    STORAGE_PROVIDER: str = "local"

    # JWT signing key (Keep secret in production!)
    SECRET_KEY: str = "dev-insecure-secret-key-change-in-production-min-32-chars"
    REGISTRATION_ENCRYPTION_KEY: Optional[str] = None

    # Token expiration periods
    ACCESS_TOKEN_MINUTES: int = 15
    REFRESH_TOKEN_DAYS: int = 30

    # OTP (One-Time Password) parameters
    OTP_EXPIRES_MINUTES: int = 5
    OTP_RESEND_SECONDS: int = 60
    OTP_MAX_ATTEMPTS: int = 5
    OTP_MAX_SENDS_PER_HOUR: int = 5

    # SMS Gateway Provider Settings
    # SMS_PROVIDER options: 'console' (dev/test logger), 'fast2sms' (India real-time OTP), 'twilio'
    SMS_PROVIDER: str = "console"
    FAST2SMS_API_KEY: Optional[str] = None
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    TWILIO_FROM_NUMBER: Optional[str] = None
    SMS_FALLBACK_TO_CONSOLE: bool = True

    # Dev OTP testing support
    # DEV_FIXED_OTP will only work if ENV == 'dev' AND the phone is in ALLOWED_TEST_PHONES
    # The application will refuse to start if DEV_FIXED_OTP is set when ENV != 'dev'
    DEV_FIXED_OTP: Optional[str] = "123456"
    ALLOWED_TEST_PHONES: Union[str, List[str]] = [
        "+919876543210",
        "+919876543211",
        "+919876543212",
        "+919876543213",
        "+919876543214",
        "+919876543215",
    ]

    # CORS origins: In dev defaults to allow all, or a specific list of domains
    CORS_ORIGINS: Union[str, List[str]] = ["*"]

    @model_validator(mode="after")
    def validate_environment_guards(self) -> "Settings":
        """Safety rules from docs/CONTEXT.md:
        1. Refuse to start if DEV_FIXED_OTP is set when ENV is not dev.
        2. Refuse to start if STORAGE_PROVIDER is local in staging or prod.
        """
        if self.ENV not in ("dev", "test") and bool(self.DEV_FIXED_OTP):
            raise ValueError(
                f"Startup refused: DEV_FIXED_OTP must not be configured when ENV='{self.ENV}'"
            )

        if self.ENV in ("staging", "prod") and self.STORAGE_PROVIDER == "local":
            raise ValueError(
                f"Startup refused: STORAGE_PROVIDER cannot be 'local' in '{self.ENV}' environment"
            )

        return self

    @field_validator("ALLOWED_TEST_PHONES")
    @classmethod
    def parse_test_phones(cls, v: Union[str, List[str]]) -> List[str]:
        """Convert comma-separated phone string to a list of clean phone numbers."""
        if isinstance(v, str):
            return [phone.strip() for phone in v.split(",") if phone.strip()]
        return v

    @field_validator("CORS_ORIGINS")
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
