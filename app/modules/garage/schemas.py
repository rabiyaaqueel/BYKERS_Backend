"""Pydantic schemas for Motorcycle Garage (M03) and Maintenance (M21)."""

import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BikePhotoOut(BaseModel):
    """Photo item attached to a motorcycle."""

    id: uuid.UUID
    media_id: uuid.UUID
    url: Optional[str] = None
    display_order: int

    model_config = ConfigDict(from_attributes=True)


class BikeCreateIn(BaseModel):
    """Motorcycle creation payload matching the 'Add a motorcycle' screen."""

    make: str = Field(..., min_length=1, max_length=100)
    model: str = Field(..., min_length=1, max_length=100)
    year: int
    powertrain: str = Field(default="petrol")
    nickname: Optional[str] = Field(default=None, max_length=100)
    odometer_km: Optional[int] = None
    registration: Optional[str] = None

    @field_validator("make", "model")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Field cannot be blank")
        return s

    @field_validator("year")
    @classmethod
    def validate_year(cls, v: int) -> int:
        current_year = datetime.now(timezone.utc).year
        if v < 1950 or v > current_year + 1:
            raise ValueError(f"Year must be between 1950 and {current_year + 1}")
        return v

    @field_validator("powertrain")
    @classmethod
    def validate_powertrain(cls, v: str) -> str:
        s = v.strip().lower()
        if s not in ("petrol", "electric", "hybrid"):
            raise ValueError("Powertrain must be 'petrol', 'electric', or 'hybrid'")
        return s

    @field_validator("odometer_km")
    @classmethod
    def validate_odometer(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 0 or v > 999999):
            raise ValueError("Odometer must be between 0 and 999,999 km")
        return v

    @field_validator("registration")
    @classmethod
    def validate_reg(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = re.sub(r"[\s\-]", "", v.strip()).upper()
        if not re.fullmatch(r"^[A-Z0-9]{6,12}$", cleaned):
            raise ValueError(
                "Registration number must be 6 to 12 alphanumeric characters without symbols"
            )
        return cleaned


class BikePatchIn(BaseModel):
    """Motorcycle update payload with optimistic concurrency version."""

    version: int = Field(
        ..., description="Current version of the motorcycle record for concurrency check"
    )
    make: Optional[str] = Field(default=None, min_length=1, max_length=100)
    model: Optional[str] = Field(default=None, min_length=1, max_length=100)
    year: Optional[int] = None
    powertrain: Optional[str] = None
    nickname: Optional[str] = Field(default=None, max_length=100)
    odometer_km: Optional[int] = None
    registration: Optional[str] = None

    @field_validator("make", "model")
    @classmethod
    def validate_patch_non_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            s = v.strip()
            if not s:
                raise ValueError("Field cannot be blank")
            return s
        return v

    @field_validator("year")
    @classmethod
    def validate_patch_year(cls, v: Optional[int]) -> Optional[int]:
        if v is not None:
            current_year = datetime.now(timezone.utc).year
            if v < 1950 or v > current_year + 1:
                raise ValueError(f"Year must be between 1950 and {current_year + 1}")
        return v

    @field_validator("powertrain")
    @classmethod
    def validate_patch_powertrain(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            s = v.strip().lower()
            if s not in ("petrol", "electric", "hybrid"):
                raise ValueError("Powertrain must be 'petrol', 'electric', or 'hybrid'")
            return s
        return v

    @field_validator("odometer_km")
    @classmethod
    def validate_patch_odometer(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 0 or v > 999999):
            raise ValueError("Odometer must be between 0 and 999,999 km")
        return v

    @field_validator("registration")
    @classmethod
    def validate_patch_reg(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v != "":
            cleaned = re.sub(r"[\s\-]", "", v.strip()).upper()
            if not re.fullmatch(r"^[A-Z0-9]{6,12}$", cleaned):
                raise ValueError(
                    "Registration number must be 6 to 12 alphanumeric characters without symbols"
                )
            return cleaned
        return v


class BikeOut(BaseModel):
    """Public/private motorcycle response with masked registration."""

    id: uuid.UUID
    make: str
    model: str
    year: int
    powertrain: str
    nickname: Optional[str] = None
    odometer_km: Optional[int] = None
    registration_masked: Optional[str] = None
    is_preferred: bool
    photos: List[BikePhotoOut] = Field(default_factory=list)
    created_at: datetime
    version: int
    archived_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class BikePhotoUploadIntentIn(BaseModel):
    """Request signed upload URL for a bike avatar photo."""

    mime_type: str = Field(..., examples=["image/jpeg", "image/png", "image/webp"])
    byte_size: Optional[int] = Field(default=None)
    bytes: Optional[int] = Field(default=None)
    display_order: int = Field(default=0, ge=0, le=4)

    @field_validator("mime_type")
    @classmethod
    def validate_mime(cls, v: str) -> str:
        allowed = ("image/jpeg", "image/png", "image/webp")
        if v.lower().strip() not in allowed:
            raise ValueError("Allowed image MIME types are image/jpeg, image/png, and image/webp")
        return v.lower().strip()

    @field_validator("byte_size")
    @classmethod
    def validate_size(cls, v: Optional[int]) -> Optional[int]:
        max_bytes = 5 * 1024 * 1024  # 5 MB
        if v is not None:
            if v <= 0:
                raise ValueError("File size must be greater than 0")
            if v > max_bytes:
                raise ValueError(f"File size exceeds 5 MB limit ({v} bytes provided)")
        return v

    @field_validator("bytes")
    @classmethod
    def validate_bytes(cls, v: Optional[int]) -> Optional[int]:
        max_bytes = 5 * 1024 * 1024  # 5 MB
        if v is not None:
            if v <= 0:
                raise ValueError("File size must be greater than 0")
            if v > max_bytes:
                raise ValueError(f"File size exceeds 5 MB limit ({v} bytes provided)")
        return v

    @model_validator(mode="after")
    def check_size_provided(self) -> "BikePhotoUploadIntentIn":
        if self.byte_size is None and self.bytes is None:
            raise ValueError("File size in bytes must be provided")
        if self.bytes is not None and self.byte_size is None:
            self.byte_size = self.bytes
        elif self.byte_size is not None and self.bytes is None:
            self.bytes = self.byte_size
        return self


class BikePhotoUploadIntentOut(BaseModel):
    media_id: uuid.UUID
    upload_url: str
    object_key: str
    expires_in_seconds: int = 900


class BikePhotoCompleteIn(BaseModel):
    media_id: uuid.UUID
    display_order: int = Field(default=0, ge=0, le=4)


class MaintenanceRecordIn(BaseModel):
    """New service maintenance log entry."""

    service_date: datetime
    odometer_km: int = Field(..., ge=0, le=999999)
    category: str = Field(..., min_length=1, max_length=100)
    notes: Optional[str] = None
    invoice_media_id: Optional[uuid.UUID] = None
    odometer_source: str = Field(default="manual")
    next_due_date: Optional[datetime] = None
    next_due_km: Optional[int] = Field(default=None, ge=0, le=999999)

    @field_validator("odometer_source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        s = v.strip().lower()
        if s not in ("manual", "imported"):
            raise ValueError("odometer_source must be 'manual' or 'imported'")
        return s


class MaintenanceRecordOut(BaseModel):
    id: uuid.UUID
    bike_id: uuid.UUID
    service_date: datetime
    odometer_km: int
    category: str
    notes: Optional[str] = None
    invoice_media_id: Optional[uuid.UUID] = None
    invoice_url: Optional[str] = None
    odometer_source: str
    next_due_date: Optional[datetime] = None
    next_due_km: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BikeDocumentIn(BaseModel):
    """Upload or record motorcycle legal documentation."""

    type: str = Field(..., examples=["insurance", "registration", "pollution", "licence"])
    expires_on: Optional[datetime] = None
    private_media_id: uuid.UUID
    sharing_policy: str = Field(default="private")

    @field_validator("type")
    @classmethod
    def validate_doc_type(cls, v: str) -> str:
        allowed = ("insurance", "registration", "pollution", "licence")
        if v.lower().strip() not in allowed:
            raise ValueError(f"Document type must be one of {allowed}")
        return v.lower().strip()

    @field_validator("sharing_policy")
    @classmethod
    def validate_sharing(cls, v: str) -> str:
        allowed = ("private", "shared_for_transaction")
        if v.lower().strip() not in allowed:
            raise ValueError(f"Sharing policy must be one of {allowed}")
        return v.lower().strip()


class BikeDocumentOut(BaseModel):
    id: uuid.UUID
    bike_id: uuid.UUID
    type: str
    expires_on: Optional[datetime] = None
    private_media_id: uuid.UUID
    download_url: Optional[str] = None
    sharing_policy: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReminderOut(BaseModel):
    id: uuid.UUID
    bike_id: uuid.UUID
    kind: str
    due_on: datetime
    cycle_key: str
    sent_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MediaUploadIntentIn(BaseModel):
    mime_type: str = Field(..., examples=["application/pdf", "image/jpeg", "image/png"])
    byte_size: Optional[int] = Field(default=None)
    bytes: Optional[int] = Field(default=None)

    @field_validator("mime_type")
    @classmethod
    def validate_mime(cls, v: str) -> str:
        allowed = ("application/pdf", "image/jpeg", "image/png", "image/webp")
        if v.lower().strip() not in allowed:
            raise ValueError(
                "Allowed MIME types are application/pdf, image/jpeg, image/png, and image/webp"
            )
        return v.lower().strip()

    @model_validator(mode="after")
    def check_size(self) -> "MediaUploadIntentIn":
        size = self.bytes or self.byte_size
        if size is None or size <= 0:
            raise ValueError("File size must be greater than 0")
        if size > 10 * 1024 * 1024:
            raise ValueError("File size exceeds 10 MB limit")
        self.byte_size = size
        self.bytes = size
        return self


class MediaUploadIntentOut(BaseModel):
    media_id: uuid.UUID
    upload_url: str
    object_key: str
    expires_in_seconds: int = 900


class MediaCompleteIn(BaseModel):
    media_id: uuid.UUID
