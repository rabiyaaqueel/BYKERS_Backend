"""Pydantic Request and Response Schemas for Authentication and Sessions."""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class DeviceIn(BaseModel):
    """Client device information."""

    platform: str = Field(default="android", description="Platform identifier (android, ios, web)")
    name: str = Field(default="Mobile Device", description="Human-readable device model name")
    push_token: Optional[str] = Field(
        default=None, description="FCM / APNS push notification token"
    )


class OTPRequestIn(BaseModel):
    """Phone OTP challenge request."""

    country_code: str = Field(
        default="+91",
        pattern=r"^\+[1-9]\d{0,3}$",
        description="E.164 country calling code (default +91 for India)",
    )
    phone: str = Field(
        ...,
        min_length=7,
        max_length=15,
        description="Phone number without country code or in full",
    )
    device: Optional[DeviceIn] = Field(default=None, description="Requesting device metadata")


class OTPRequestOut(BaseModel):
    """Neutral OTP response to prevent user enumeration."""

    message: str = Field(
        default="If the phone number is valid, a verification code has been sent.",
        description="Neutral status message",
    )
    resend_in_seconds: int = Field(
        default=60, description="Minimum seconds before another OTP can be requested"
    )


class OTPVerifyIn(BaseModel):
    """OTP verification payload."""

    phone: str = Field(
        ..., min_length=7, max_length=20, description="Normalized or raw phone number"
    )
    otp: str = Field(..., min_length=4, max_length=8, description="Verification code received")
    device: Optional[DeviceIn] = Field(default=None, description="Device completing verification")


class AuthTokenOut(BaseModel):
    """Token response on successful login or refresh."""

    access_token: str = Field(description="Signed JWT access token (15 mins)")
    refresh_token: str = Field(
        description="Rotating cryptographically secure refresh token (30 days)"
    )
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(default=900, description="Access token expiration in seconds")
    account_status: str = Field(
        description="Current account state (e.g. pending_verification, active)"
    )
    onboarding_required: bool = Field(
        description="True if rider has not completed initial profile setup"
    )


class RefreshTokenIn(BaseModel):
    """Refresh token payload."""

    refresh_token: str = Field(..., description="Active rotating refresh token")


class SessionOut(BaseModel):
    """Redacted session and device metadata for device management."""

    id: uuid.UUID
    interface: str
    platform: str
    device_name: str
    created_at: datetime
    last_active_at: datetime
    is_current: bool = False

    model_config = ConfigDict(from_attributes=True)


class LogoutOut(BaseModel):
    """Logout confirmation payload."""

    message: str = Field(default="Successfully logged out", description="Status message")
