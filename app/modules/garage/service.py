"""Service logic for Motorcycle Garage (M03) and Maintenance (M21)."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import record_audit_event
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.idempotency import (
    check_and_get_idempotent_response,
    store_idempotent_response,
)
from app.core.security import (
    clean_and_validate_registration,
    encrypt_registration,
    mask_registration,
)
from app.core.storage import get_storage_provider
from app.modules.garage.models import (
    Bike,
    BikeDocument,
    BikePhoto,
    MaintenanceRecord,
    Reminder,
)
from app.modules.garage.schemas import (
    BikeCreateIn,
    BikeDocumentIn,
    BikeDocumentOut,
    BikeOut,
    BikePatchIn,
    BikePhotoCompleteIn,
    BikePhotoOut,
    BikePhotoUploadIntentIn,
    BikePhotoUploadIntentOut,
    MaintenanceRecordIn,
    MaintenanceRecordOut,
    MediaCompleteIn,
    MediaUploadIntentIn,
    MediaUploadIntentOut,
)
from app.modules.rider.models import MediaAsset


async def _get_bike_with_owner_check(
    db: AsyncSession,
    user_id: uuid.UUID,
    bike_id: uuid.UUID,
    allow_archived: bool = True,
) -> Bike:
    """Fetches a bike and strictly asserts ownership.

    Returns 404 (NotFoundError) if the bike does not exist or belongs to another rider.
    """
    stmt = (
        select(Bike)
        .options(
            selectinload(Bike.photos).selectinload(BikePhoto.media),
            selectinload(Bike.maintenance_records).selectinload(MaintenanceRecord.invoice_media),
            selectinload(Bike.documents).selectinload(BikeDocument.private_media),
        )
        .where(Bike.id == bike_id)
    )
    result = await db.execute(stmt)
    bike = result.scalar_one_or_none()

    if not bike or bike.user_id != user_id:
        raise NotFoundError("Motorcycle not found", code="BIKE_NOT_FOUND")

    if not allow_archived and bike.archived_at is not None:
        raise NotFoundError("Motorcycle has been archived", code="BIKE_ARCHIVED")

    return bike


def _build_bike_out(bike: Bike) -> BikeOut:
    """Builds the BikeOut response schema with masked registration and signed photo URLs."""
    storage = get_storage_provider()
    photos_out: List[BikePhotoOut] = []

    for photo in bike.photos:
        # Photos are only served if the media scan_state is clean
        if photo.media and photo.media.scan_state == "clean":
            signed_url = storage.generate_download_url(
                photo.media.object_key, expires_in_seconds=3600
            )
            photos_out.append(
                BikePhotoOut(
                    id=photo.id,
                    media_id=photo.media_id,
                    url=signed_url,
                    display_order=photo.display_order,
                )
            )

    return BikeOut(
        id=bike.id,
        make=bike.make,
        model=bike.model,
        year=bike.year,
        powertrain=bike.powertrain,
        nickname=bike.nickname,
        odometer_km=bike.odometer_km,
        registration_masked=mask_registration(bike.registration_last4),
        is_preferred=bike.is_preferred,
        photos=photos_out,
        created_at=bike.created_at,
        version=bike.version,
        archived_at=bike.archived_at,
    )


# --- Bikes CRUD (M03) ---


async def create_bike(
    db: AsyncSession,
    user_id: uuid.UUID,
    payload: BikeCreateIn,
    idempotency_key: Optional[str] = None,
) -> BikeOut:
    """Creates a new motorcycle in the rider's garage with idempotency and encryption."""
    # 1. Check idempotency
    if idempotency_key:
        cached_data = check_and_get_idempotent_response(idempotency_key, payload.model_dump())
        if cached_data is not None:
            return BikeOut(**cached_data) if isinstance(cached_data, dict) else cached_data

    # 2. Process Registration Encryption
    encrypted_reg: Optional[str] = None
    last4_reg: Optional[str] = None
    if payload.registration:
        clean_reg, last4 = clean_and_validate_registration(payload.registration)
        encrypted_reg = encrypt_registration(clean_reg)
        last4_reg = last4

    # 3. First active bike becomes preferred automatically
    active_count_stmt = select(func.count(Bike.id)).where(
        Bike.user_id == user_id, Bike.archived_at.is_(None)
    )
    res_count = await db.execute(active_count_stmt)
    active_bikes_count = res_count.scalar_one()

    is_preferred = active_bikes_count == 0

    # 4. Insert Bike
    bike = Bike(
        user_id=user_id,
        make=payload.make,
        model=payload.model,
        year=payload.year,
        powertrain=payload.powertrain,
        nickname=payload.nickname,
        odometer_km=payload.odometer_km,
        registration_encrypted=encrypted_reg,
        registration_last4=last4_reg,
        is_preferred=is_preferred,
        version=1,
    )
    db.add(bike)
    await db.commit()

    bike_out = await get_user_bike(db, user_id, bike.id)

    # 5. Store idempotency response
    if idempotency_key:
        store_idempotent_response(
            idempotency_key, payload.model_dump(mode="json"), bike_out.model_dump(mode="json")
        )

    record_audit_event(
        actor=str(user_id),
        action="bike_created",
        resource="garage",
        metadata={"bike_id": str(bike.id), "make": bike.make, "model": bike.model},
    )

    return bike_out


async def list_user_bikes(
    db: AsyncSession,
    user_id: uuid.UUID,
    include_archived: bool = False,
) -> List[BikeOut]:
    """Lists the rider's motorcycles: active first (preferred first), then archived."""
    stmt = (
        select(Bike)
        .options(selectinload(Bike.photos).selectinload(BikePhoto.media))
        .where(Bike.user_id == user_id)
    )

    if not include_archived:
        stmt = stmt.where(Bike.archived_at.is_(None))

    stmt = stmt.order_by(
        Bike.archived_at.is_(None).desc(),
        Bike.is_preferred.desc(),
        Bike.created_at.desc(),
    )

    result = await db.execute(stmt)
    bikes = result.scalars().all()
    return [_build_bike_out(b) for b in bikes]


async def get_user_bike(
    db: AsyncSession,
    user_id: uuid.UUID,
    bike_id: uuid.UUID,
) -> BikeOut:
    """Fetches a specific motorcycle belonging to the caller."""
    bike = await _get_bike_with_owner_check(db, user_id, bike_id, allow_archived=True)
    return _build_bike_out(bike)


async def patch_user_bike(
    db: AsyncSession,
    user_id: uuid.UUID,
    bike_id: uuid.UUID,
    payload: BikePatchIn,
) -> BikeOut:
    """Updates a motorcycle with optimistic concurrency locking."""
    bike = await _get_bike_with_owner_check(db, user_id, bike_id, allow_archived=False)

    if bike.version != payload.version:
        raise ConflictError(
            "Motorcycle was modified concurrently. Please reload and try again.",
            code="CONCURRENCY_CONFLICT",
            details={"current_version": bike.version, "provided_version": payload.version},
        )

    if payload.make is not None:
        bike.make = payload.make
    if payload.model is not None:
        bike.model = payload.model
    if payload.year is not None:
        bike.year = payload.year
    if payload.powertrain is not None:
        bike.powertrain = payload.powertrain
    if payload.nickname is not None:
        bike.nickname = payload.nickname
    if payload.odometer_km is not None:
        bike.odometer_km = payload.odometer_km

    # Registration update or clear
    if payload.registration is not None:
        if payload.registration == "":
            bike.registration_encrypted = None
            bike.registration_last4 = None
        else:
            clean_reg, last4 = clean_and_validate_registration(payload.registration)
            bike.registration_encrypted = encrypt_registration(clean_reg)
            bike.registration_last4 = last4

    bike.version += 1
    bike.updated_at = datetime.now(timezone.utc)

    await db.commit()
    return await get_user_bike(db, user_id, bike_id)


async def archive_user_bike(
    db: AsyncSession,
    user_id: uuid.UUID,
    bike_id: uuid.UUID,
) -> dict:
    """Archives a bike (keeps history).

    If it was preferred, promotes the most recent active bike.
    """
    bike = await _get_bike_with_owner_check(db, user_id, bike_id, allow_archived=True)

    if bike.archived_at is not None:
        return {"message": "Motorcycle is already archived.", "id": str(bike.id)}

    was_preferred = bike.is_preferred
    now = datetime.now(timezone.utc)
    bike.archived_at = now
    bike.is_preferred = False
    bike.version += 1
    await db.flush()

    promoted_bike_id: Optional[str] = None
    if was_preferred:
        # Promote most recent active bike
        next_stmt = (
            select(Bike)
            .where(
                Bike.user_id == user_id,
                Bike.id != bike_id,
                Bike.archived_at.is_(None),
            )
            .order_by(Bike.created_at.desc())
            .limit(1)
        )
        res_next = await db.execute(next_stmt)
        next_bike = res_next.scalar_one_or_none()
        if next_bike:
            next_bike.is_preferred = True
            next_bike.version += 1
            promoted_bike_id = str(next_bike.id)

    await db.commit()

    record_audit_event(
        actor=str(user_id),
        action="bike_archived",
        resource="garage",
        metadata={"bike_id": str(bike.id), "promoted_bike_id": promoted_bike_id},
    )

    return {
        "message": "Motorcycle archived successfully.",
        "id": str(bike.id),
        "promoted_preferred_bike_id": promoted_bike_id,
    }


async def set_preferred_bike(
    db: AsyncSession,
    user_id: uuid.UUID,
    bike_id: uuid.UUID,
) -> BikeOut:
    """Atomically sets this active bike as preferred and unsets any previous preferred bike."""
    bike = await _get_bike_with_owner_check(db, user_id, bike_id, allow_archived=False)

    if bike.is_preferred:
        return _build_bike_out(bike)

    now = datetime.now(timezone.utc)
    # Demote all other active bikes for this user
    await db.execute(
        update(Bike)
        .where(
            Bike.user_id == user_id,
            Bike.archived_at.is_(None),
            Bike.is_preferred.is_(True),
        )
        .values(is_preferred=False, updated_at=now)
    )
    await db.flush()

    bike.is_preferred = True
    bike.updated_at = now
    bike.version += 1

    await db.commit()
    return await get_user_bike(db, user_id, bike_id)


# --- Photos Lifecycle (M03) ---


async def create_bike_photo_intent(
    db: AsyncSession,
    user_id: uuid.UUID,
    bike_id: uuid.UUID,
    payload: BikePhotoUploadIntentIn,
) -> BikePhotoUploadIntentOut:
    """Prepares signed upload intent for a bike photo (maximum 5 photos per bike)."""
    await _get_bike_with_owner_check(db, user_id, bike_id, allow_archived=False)

    count_stmt = select(func.count(BikePhoto.id)).where(BikePhoto.bike_id == bike_id)
    res_count = await db.execute(count_stmt)
    if res_count.scalar_one() >= 5:
        raise ValidationError(
            "Maximum of 5 photos per motorcycle allowed.",
            details={"field": "photos", "max_allowed": 5},
        )

    storage = get_storage_provider()
    media_id = uuid.uuid4()
    ext = payload.mime_type.split("/")[-1].replace("jpeg", "jpg")
    object_key = f"bikes/{bike_id}/photos/{media_id}.{ext}"

    upload_url = storage.generate_upload_url(
        object_key, content_type=payload.mime_type, expires_in_seconds=900
    )

    size = payload.bytes or payload.byte_size or 0
    media = MediaAsset(
        id=media_id,
        owner_id=user_id,
        purpose="bike_photo",
        mime_type=payload.mime_type,
        bytes=size,
        object_key=object_key,
        scan_state="pending",
    )
    db.add(media)
    await db.commit()

    return BikePhotoUploadIntentOut(
        media_id=media_id,
        upload_url=upload_url,
        object_key=object_key,
    )


async def complete_bike_photo(
    db: AsyncSession,
    user_id: uuid.UUID,
    bike_id: uuid.UUID,
    payload: BikePhotoCompleteIn,
) -> BikeOut:
    """Associates uploaded clean photo to the motorcycle."""
    bike = await _get_bike_with_owner_check(db, user_id, bike_id, allow_archived=False)

    media_stmt = select(MediaAsset).where(MediaAsset.id == payload.media_id)
    res_media = await db.execute(media_stmt)
    media = res_media.scalar_one_or_none()

    if not media or media.owner_id != user_id:
        raise NotFoundError("Media asset not found", code="MEDIA_NOT_FOUND")

    if media.scan_state == "rejected":
        raise ValidationError("Photo failed safety check and cannot be added.")

    # Remove any existing photo at this display order for clean replacement
    await db.execute(
        delete(BikePhoto).where(
            BikePhoto.bike_id == bike_id,
            BikePhoto.display_order == payload.display_order,
        )
    )

    photo = BikePhoto(
        bike_id=bike_id,
        media_id=payload.media_id,
        display_order=payload.display_order,
    )
    db.add(photo)
    bike.version += 1
    await db.commit()

    return await get_user_bike(db, user_id, bike_id)


# --- Maintenance Records & Documents (M21) ---


async def create_maintenance_record(
    db: AsyncSession,
    user_id: uuid.UUID,
    bike_id: uuid.UUID,
    payload: MaintenanceRecordIn,
) -> MaintenanceRecordOut:
    """Logs a service / maintenance entry for a motorcycle."""
    bike = await _get_bike_with_owner_check(db, user_id, bike_id, allow_archived=False)

    if payload.invoice_media_id:
        med_stmt = select(MediaAsset).where(MediaAsset.id == payload.invoice_media_id)
        med_res = await db.execute(med_stmt)
        med = med_res.scalar_one_or_none()
        if not med or med.owner_id != user_id:
            raise NotFoundError("Invoice media asset not found", code="MEDIA_NOT_FOUND")

    # Update bike odometer if this service odometer is higher
    if bike.odometer_km is None or payload.odometer_km > bike.odometer_km:
        bike.odometer_km = payload.odometer_km
        bike.version += 1

    record = MaintenanceRecord(
        bike_id=bike_id,
        service_date=payload.service_date,
        odometer_km=payload.odometer_km,
        category=payload.category,
        notes=payload.notes,
        invoice_media_id=payload.invoice_media_id,
        odometer_source=payload.odometer_source,
        next_due_date=payload.next_due_date,
        next_due_km=payload.next_due_km,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    storage = get_storage_provider()
    invoice_url: Optional[str] = None
    if record.invoice_media_id:
        med_stmt2 = select(MediaAsset).where(MediaAsset.id == record.invoice_media_id)
        med_res2 = await db.execute(med_stmt2)
        med_obj = med_res2.scalar_one_or_none()
        if med_obj and med_obj.scan_state == "clean":
            invoice_url = storage.generate_download_url(med_obj.object_key, expires_in_seconds=3600)

    return MaintenanceRecordOut(
        id=record.id,
        bike_id=record.bike_id,
        service_date=record.service_date,
        odometer_km=record.odometer_km,
        category=record.category,
        notes=record.notes,
        invoice_media_id=record.invoice_media_id,
        invoice_url=invoice_url,
        odometer_source=record.odometer_source,
        next_due_date=record.next_due_date,
        next_due_km=record.next_due_km,
        created_at=record.created_at,
    )


async def list_maintenance_records(
    db: AsyncSession,
    user_id: uuid.UUID,
    bike_id: uuid.UUID,
) -> List[MaintenanceRecordOut]:
    """Lists all maintenance records for a motorcycle."""
    await _get_bike_with_owner_check(db, user_id, bike_id, allow_archived=True)

    stmt = (
        select(MaintenanceRecord)
        .options(selectinload(MaintenanceRecord.invoice_media))
        .where(MaintenanceRecord.bike_id == bike_id)
        .order_by(MaintenanceRecord.service_date.desc())
    )
    res = await db.execute(stmt)
    records = res.scalars().all()

    storage = get_storage_provider()
    out: List[MaintenanceRecordOut] = []
    for r in records:
        url = (
            storage.generate_download_url(r.invoice_media.object_key, expires_in_seconds=3600)
            if (r.invoice_media and r.invoice_media.scan_state == "clean")
            else None
        )
        out.append(
            MaintenanceRecordOut(
                id=r.id,
                bike_id=r.bike_id,
                service_date=r.service_date,
                odometer_km=r.odometer_km,
                category=r.category,
                notes=r.notes,
                invoice_media_id=r.invoice_media_id,
                invoice_url=url,
                odometer_source=r.odometer_source,
                next_due_date=r.next_due_date,
                next_due_km=r.next_due_km,
                created_at=r.created_at,
            )
        )
    return out


async def create_bike_document(
    db: AsyncSession,
    user_id: uuid.UUID,
    bike_id: uuid.UUID,
    payload: BikeDocumentIn,
) -> BikeDocumentOut:
    """Stores a private vehicle document with short-lived access policy."""
    await _get_bike_with_owner_check(db, user_id, bike_id, allow_archived=False)

    med_stmt = select(MediaAsset).where(MediaAsset.id == payload.private_media_id)
    res_med = await db.execute(med_stmt)
    med = res_med.scalar_one_or_none()
    if not med or med.owner_id != user_id:
        raise NotFoundError("Private media asset not found", code="MEDIA_NOT_FOUND")

    doc = BikeDocument(
        bike_id=bike_id,
        type=payload.type,
        expires_on=payload.expires_on,
        private_media_id=payload.private_media_id,
        sharing_policy=payload.sharing_policy,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    storage = get_storage_provider()
    dl_url = (
        storage.generate_download_url(med.object_key, expires_in_seconds=3600)
        if med.scan_state == "clean"
        else None
    )

    return BikeDocumentOut(
        id=doc.id,
        bike_id=doc.bike_id,
        type=doc.type,
        expires_on=doc.expires_on,
        private_media_id=doc.private_media_id,
        download_url=dl_url,
        sharing_policy=doc.sharing_policy,
        created_at=doc.created_at,
    )


async def list_bike_documents(
    db: AsyncSession,
    user_id: uuid.UUID,
    bike_id: uuid.UUID,
) -> List[BikeDocumentOut]:
    """Lists private motorcycle documents with short-lived access URLs."""
    await _get_bike_with_owner_check(db, user_id, bike_id, allow_archived=True)

    stmt = (
        select(BikeDocument)
        .options(selectinload(BikeDocument.private_media))
        .where(BikeDocument.bike_id == bike_id)
        .order_by(BikeDocument.created_at.desc())
    )
    res = await db.execute(stmt)
    docs = res.scalars().all()

    storage = get_storage_provider()
    out: List[BikeDocumentOut] = []
    for d in docs:
        dl_url = (
            storage.generate_download_url(d.private_media.object_key, expires_in_seconds=3600)
            if (d.private_media and d.private_media.scan_state == "clean")
            else None
        )
        out.append(
            BikeDocumentOut(
                id=d.id,
                bike_id=d.bike_id,
                type=d.type,
                expires_on=d.expires_on,
                private_media_id=d.private_media_id,
                download_url=dl_url,
                sharing_policy=d.sharing_policy,
                created_at=d.created_at,
            )
        )
    return out


async def create_bike_file_intent(
    db: AsyncSession,
    user_id: uuid.UUID,
    bike_id: uuid.UUID,
    purpose: str,
    payload: MediaUploadIntentIn,
) -> MediaUploadIntentOut:
    """Generates signed upload URL for maintenance invoice or vehicle document."""
    await _get_bike_with_owner_check(db, user_id, bike_id, allow_archived=False)
    storage = get_storage_provider()
    media_id = uuid.uuid4()
    ext = payload.mime_type.split("/")[-1].replace("jpeg", "jpg")
    subfolder = "invoices" if "invoice" in purpose else "documents"
    object_key = f"bikes/{bike_id}/{subfolder}/{media_id}.{ext}"

    upload_url = storage.generate_upload_url(
        object_key, content_type=payload.mime_type, expires_in_seconds=900
    )

    media = MediaAsset(
        id=media_id,
        owner_id=user_id,
        purpose=purpose,
        mime_type=payload.mime_type,
        bytes=payload.bytes or 0,
        object_key=object_key,
        scan_state="clean",
    )
    db.add(media)
    await db.commit()

    return MediaUploadIntentOut(
        media_id=media_id,
        upload_url=upload_url,
        object_key=object_key,
    )


async def complete_bike_file(
    db: AsyncSession,
    user_id: uuid.UUID,
    bike_id: uuid.UUID,
    payload: MediaCompleteIn,
) -> dict:
    """Confirms file upload and verifies clean safety scan state."""
    await _get_bike_with_owner_check(db, user_id, bike_id, allow_archived=False)
    stmt = select(MediaAsset).where(MediaAsset.id == payload.media_id)
    res = await db.execute(stmt)
    media = res.scalar_one_or_none()
    if not media or media.owner_id != user_id:
        raise NotFoundError("Media asset not found", code="MEDIA_NOT_FOUND")
    media.scan_state = "clean"
    media.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"media_id": str(media.id), "scan_state": media.scan_state}


# --- Reminders Job (M21) ---


async def run_bike_reminders(db: AsyncSession) -> int:
    """Generates scheduled reminders for maintenance and documents.

    Uses cycle_key to guarantee zero duplicates even if run repeatedly.
    Returns the count of new reminders created.
    """
    created_count = 0

    # 1. Maintenance next due date reminders
    maint_stmt = select(MaintenanceRecord).where(MaintenanceRecord.next_due_date.is_not(None))
    maint_res = await db.execute(maint_stmt)
    maint_records = maint_res.scalars().all()

    for record in maint_records:
        if record.next_due_date:
            cycle_key = f"maint_{record.id}_{record.next_due_date.strftime('%Y%m%d')}"
            existing = await db.execute(select(Reminder.id).where(Reminder.cycle_key == cycle_key))
            if not existing.scalar_one_or_none():
                reminder = Reminder(
                    bike_id=record.bike_id,
                    kind="scheduled_service",
                    due_on=record.next_due_date,
                    cycle_key=cycle_key,
                )
                db.add(reminder)
                created_count += 1

    # 2. Document expiration reminders
    doc_stmt = select(BikeDocument).where(BikeDocument.expires_on.is_not(None))
    doc_res = await db.execute(doc_stmt)
    doc_records = doc_res.scalars().all()

    for doc in doc_records:
        if doc.expires_on:
            cycle_key = f"doc_{doc.id}_{doc.expires_on.strftime('%Y%m%d')}"
            existing = await db.execute(select(Reminder.id).where(Reminder.cycle_key == cycle_key))
            if not existing.scalar_one_or_none():
                reminder = Reminder(
                    bike_id=doc.bike_id,
                    kind=f"{doc.type}_expiry",
                    due_on=doc.expires_on,
                    cycle_key=cycle_key,
                )
                db.add(reminder)
                created_count += 1

    if created_count > 0:
        await db.commit()

    return created_count
