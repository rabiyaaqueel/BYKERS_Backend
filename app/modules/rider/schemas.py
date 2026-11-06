"""Pydantic schemas for Rider Onboarding, Profile, and Consents."""

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CityOut(BaseModel):
    id: uuid.UUID
    name: str
    state: str
    country: str
    active: bool

    model_config = ConfigDict(from_attributes=True)


class InterestOut(BaseModel):
    id: uuid.UUID
    code: str
    name_en: str
    name_te: str
    name_hi: str

    model_config = ConfigDict(from_attributes=True)


class NoticeVersionOut(BaseModel):
    kind: str
    version: str
    published_at: datetime
    text_url: str

    model_config = ConfigDict(from_attributes=True)


class NoticeCurrentOut(BaseModel):
    terms: Optional[NoticeVersionOut] = None
    privacy: Optional[NoticeVersionOut] = None


class AccountSetupIn(BaseModel):
    display_name: str = Field(..., min_length=2, max_length=100)
    city_id: Optional[uuid.UUID] = None
    locale: str = Field(default="en", max_length=10)
    adult_declaration: bool
    accepted_terms_version: str
    accepted_privacy_version: str
    marketing_consent: bool = False
    interests: List[str] = Field(default_factory=list)

    @field_validator("adult_declaration")
    @classmethod
    def validate_adult(cls, v: bool) -> bool:
        if not v:
            raise ValueError("You must declare that you are at least 18 years old to proceed.")
        return v


class AcceptNoticesIn(BaseModel):
    accepted_terms_version: Optional[str] = None
    accepted_privacy_version: Optional[str] = None


class ProfilePatchIn(BaseModel):
    display_name: Optional[str] = Field(None, min_length=2, max_length=100)
    bio: Optional[str] = Field(None, max_length=500)
    home_city_id: Optional[uuid.UUID] = None
    experience: Optional[str] = None  # beginner, intermediate, experienced
    visibility: Optional[str] = None  # all_riders, connections, private
    languages: Optional[List[str]] = None
    interests: Optional[List[str]] = None  # list of codes
    legal_name: Optional[str] = Field(None, max_length=150)
    email: Optional[str] = Field(None, max_length=255)

    @field_validator("experience")
    @classmethod
    def validate_exp(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("beginner", "intermediate", "experienced"):
            raise ValueError("Experience must be 'beginner', 'intermediate', or 'experienced'")
        return v

    @field_validator("visibility")
    @classmethod
    def validate_vis(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("all_riders", "connections", "private"):
            raise ValueError("Visibility must be 'all_riders', 'connections', or 'private'")
        return v


class PublicProfileOut(BaseModel):
    user_id: uuid.UUID
    display_name: str
    photo_url: Optional[str] = None
    city: Optional[str] = None
    bio: Optional[str] = None
    experience: str
    visibility: str
    languages: List[str] = Field(default_factory=list)
    interests: List[InterestOut] = Field(default_factory=list)
    verified_badges: List[str] = Field(default_factory=list)
    message: Optional[str] = None


class PrivateDetailsOut(BaseModel):
    legal_name: Optional[str] = None
    email: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ConsentEventOut(BaseModel):
    id: uuid.UUID
    purpose: str
    action: str
    notice_version: Optional[str] = None
    occurred_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConsentUpdateIn(BaseModel):
    purpose: str
    action: str  # granted, withdrawn

    @field_validator("action")
    @classmethod
    def validate_act(cls, v: str) -> str:
        if v not in ("granted", "withdrawn"):
            raise ValueError("Action must be 'granted' or 'withdrawn'")
        return v

    @field_validator("purpose")
    @classmethod
    def validate_purp(cls, v: str) -> str:
        allowed = (
            "terms",
            "privacy",
            "nearby_discovery",
            "ride_recording",
            "live_sharing",
            "public_routes",
            "public_leaderboard",
            "marketing",
            "device_location",
        )
        if v not in allowed:
            raise ValueError(f"Purpose must be one of {allowed}")
        return v


class PhotoUploadIntentIn(BaseModel):
    filename: str
    mime_type: str
    bytes: int

    @field_validator("mime_type")
    @classmethod
    def validate_mime(cls, v: str) -> str:
        allowed = ("image/jpeg", "image/png", "image/webp")
        if v not in allowed:
            raise ValueError(f"MIME type '{v}' not supported. Allowed: {allowed}")
        return v

    @field_validator("bytes")
    @classmethod
    def validate_size(cls, v: int) -> int:
        max_bytes = 5 * 1024 * 1024  # 5 MB
        if v <= 0:
            raise ValueError("File size must be greater than 0")
        if v > max_bytes:
            raise ValueError(f"File size exceeds 5 MB limit ({v} bytes provided)")
        return v


class PhotoUploadIntentOut(BaseModel):
    media_asset_id: uuid.UUID
    upload_url: str
    object_key: str
    expires_in_seconds: int = 900


class PhotoCompleteIn(BaseModel):
    media_asset_id: uuid.UUID


class PhotoCompleteOut(BaseModel):
    media_asset_id: uuid.UUID
    scan_state: str
    photo_url: Optional[str] = None


class ExtendedMeOut(BaseModel):
    id: uuid.UUID
    phone_masked: str
    status: str
    onboarding_required: bool
    account_setup_completed: bool
    locale: str
    profile: Optional[PublicProfileOut] = None
    private_details: Optional[PrivateDetailsOut] = None
    consents: Dict[str, str] = Field(default_factory=dict)
    verified_badges: List[str] = Field(default_factory=list)
