"""SQLAlchemy Database Models for Motorcycle Garage (M03) and Maintenance (M21)."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Bike(Base):
    """Motorcycle entity in a rider's garage (M03)."""

    __tablename__ = "bikes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    make: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    powertrain: Mapped[str] = mapped_column(String(20), nullable=False, default="petrol")
    nickname: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    odometer_km: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    registration_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    registration_last4: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    is_preferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Relationships
    user = relationship("User", backref="bikes")
    photos: Mapped[List["BikePhoto"]] = relationship(
        "BikePhoto",
        back_populates="bike",
        cascade="all, delete-orphan",
        order_by="BikePhoto.display_order",
    )
    maintenance_records: Mapped[List["MaintenanceRecord"]] = relationship(
        "MaintenanceRecord",
        back_populates="bike",
        cascade="all, delete-orphan",
        order_by="MaintenanceRecord.service_date.desc()",
    )
    documents: Mapped[List["BikeDocument"]] = relationship(
        "BikeDocument",
        back_populates="bike",
        cascade="all, delete-orphan",
    )
    reminders: Mapped[List["Reminder"]] = relationship(
        "Reminder",
        back_populates="bike",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "powertrain IN ('petrol', 'electric', 'hybrid')", name="ck_bikes_powertrain"
        ),
        CheckConstraint("year >= 1950", name="ck_bikes_year_min"),
        CheckConstraint(
            "odometer_km IS NULL OR (odometer_km >= 0 AND odometer_km <= 999999)",
            name="ck_bikes_odometer_range",
        ),
        Index(
            "uq_bikes_user_preferred",
            "user_id",
            unique=True,
            postgresql_where=(is_preferred.is_(True) & archived_at.is_(None)),
        ),
    )


class BikePhoto(Base):
    """Photographs linked to a motorcycle (up to 5 per bike)."""

    __tablename__ = "bike_photos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bike_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bikes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    media_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    bike = relationship("Bike", back_populates="photos")
    media = relationship("MediaAsset")

    __table_args__ = (UniqueConstraint("bike_id", "display_order", name="uq_bike_photos_order"),)


class MaintenanceRecord(Base):
    """Service and maintenance history for a motorcycle (M21)."""

    __tablename__ = "maintenance_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bike_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bikes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    odometer_km: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    invoice_media_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True
    )
    odometer_source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    next_due_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_due_km: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    bike = relationship("Bike", back_populates="maintenance_records")
    invoice_media = relationship("MediaAsset")

    __table_args__ = (
        CheckConstraint("odometer_source IN ('manual', 'imported')", name="ck_maintenance_source"),
    )


class BikeDocument(Base):
    """Private documents (insurance, RC, pollution, licence) for a motorcycle."""

    __tablename__ = "bike_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bike_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bikes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    expires_on: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    private_media_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    sharing_policy: Mapped[str] = mapped_column(String(50), nullable=False, default="private")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    bike = relationship("Bike", back_populates="documents")
    private_media = relationship("MediaAsset")

    __table_args__ = (
        CheckConstraint(
            "type IN ('insurance', 'registration', 'pollution', 'licence')",
            name="ck_bike_documents_type",
        ),
        CheckConstraint(
            "sharing_policy IN ('private', 'shared_for_transaction')",
            name="ck_bike_documents_sharing",
        ),
    )


class Reminder(Base):
    """Scheduled service, maintenance, or document expiry reminder (M21)."""

    __tablename__ = "reminders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bike_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bikes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    due_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cycle_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    bike = relationship("Bike", back_populates="reminders")
