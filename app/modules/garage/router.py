"""API Router for Motorcycle Garage (M03) and Maintenance / Documents (M21).

Rider app only. All endpoints declare require_interface("rider_app") and module code M03 or M21.
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.dependencies import AuthenticatedUser, require_interface
from app.core.errors import ForbiddenError
from app.core.permissions import can
from app.modules.garage.schemas import (
    BikeCreateIn,
    BikeDocumentIn,
    BikeDocumentOut,
    BikeOut,
    BikePatchIn,
    BikePhotoCompleteIn,
    BikePhotoUploadIntentIn,
    BikePhotoUploadIntentOut,
    MaintenanceRecordIn,
    MaintenanceRecordOut,
    MediaCompleteIn,
    MediaUploadIntentIn,
    MediaUploadIntentOut,
)
from app.modules.garage.service import (
    archive_user_bike,
    complete_bike_file,
    complete_bike_photo,
    create_bike,
    create_bike_document,
    create_bike_file_intent,
    create_bike_photo_intent,
    create_maintenance_record,
    get_user_bike,
    list_bike_documents,
    list_maintenance_records,
    list_user_bikes,
    patch_user_bike,
    set_preferred_bike,
)

garage_router = APIRouter(prefix="/me/bikes", tags=["Motorcycle Garage (M03 & M21)"])


def require_module_code(code: str):
    """Enforces both rider_app interface and active module enablement in one dependency."""

    async def _dependency(
        user: AuthenticatedUser = Depends(require_interface("rider_app")),
        db: AsyncSession = Depends(get_db),
    ) -> AuthenticatedUser:
        allowed, reason = await can(
            db=db,
            user=user,
            action="",
            module_code=code,
            allowed_interfaces=("rider_app",),
        )
        if not allowed:
            raise ForbiddenError(reason, code="MODULE_DISABLED")
        return user

    return _dependency


# ==============================================================================
# M03: Motorcycle Garage Basics
# ==============================================================================


@garage_router.post(
    "",
    response_model=BikeOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a Motorcycle",
    description=(
        "M03 - Motorcycle Garage. Rider app only. Supports Idempotency-Key. "
        "Encrypts registration at rest."
    ),
    openapi_extra={"module_code": "M03"},
)
async def api_create_bike(
    payload: BikeCreateIn,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(require_module_code("M03")),
    db: AsyncSession = Depends(get_db),
) -> BikeOut:
    return await create_bike(
        db=db,
        user_id=current_user.user_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@garage_router.get(
    "",
    response_model=List[BikeOut],
    summary="List Garage Motorcycles",
    description=(
        "M03 - Motorcycle Garage. Rider app only. Active first (preferred first), "
        "then archived if include_archived=true."
    ),
    openapi_extra={"module_code": "M03"},
)
async def api_list_bikes(
    include_archived: bool = Query(False, description="Include archived motorcycles in list"),
    current_user: AuthenticatedUser = Depends(require_module_code("M03")),
    db: AsyncSession = Depends(get_db),
) -> List[BikeOut]:
    return await list_user_bikes(
        db=db,
        user_id=current_user.user_id,
        include_archived=include_archived,
    )


@garage_router.get(
    "/{bike_id}",
    response_model=BikeOut,
    summary="Get Motorcycle Details",
    description=(
        "M03 - Motorcycle Garage. Rider app only. Returns 404 for bikes owned by other riders."
    ),
    openapi_extra={"module_code": "M03"},
)
async def api_get_bike(
    bike_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_module_code("M03")),
    db: AsyncSession = Depends(get_db),
) -> BikeOut:
    return await get_user_bike(db=db, user_id=current_user.user_id, bike_id=bike_id)


@garage_router.patch(
    "/{bike_id}",
    response_model=BikeOut,
    summary="Update Motorcycle Details",
    description=(
        "M03 - Motorcycle Garage. Requires version for optimistic concurrency (409 on mismatch)."
    ),
    openapi_extra={"module_code": "M03"},
)
async def api_patch_bike(
    bike_id: uuid.UUID,
    payload: BikePatchIn,
    current_user: AuthenticatedUser = Depends(require_module_code("M03")),
    db: AsyncSession = Depends(get_db),
) -> BikeOut:
    return await patch_user_bike(
        db=db,
        user_id=current_user.user_id,
        bike_id=bike_id,
        payload=payload,
    )


@garage_router.delete(
    "/{bike_id}",
    summary="Archive Motorcycle",
    description=(
        "M03 - Motorcycle Garage. Archives bike (retains history). "
        "Promotes most recent active bike if preferred."
    ),
    openapi_extra={"module_code": "M03"},
)
async def api_archive_bike(
    bike_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_module_code("M03")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await archive_user_bike(db=db, user_id=current_user.user_id, bike_id=bike_id)


@garage_router.post(
    "/{bike_id}/preferred",
    response_model=BikeOut,
    summary="Set Preferred Motorcycle",
    description=(
        "M03 - Motorcycle Garage. Atomically switches active preferred motorcycle for rider."
    ),
    openapi_extra={"module_code": "M03"},
)
async def api_set_preferred(
    bike_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_module_code("M03")),
    db: AsyncSession = Depends(get_db),
) -> BikeOut:
    return await set_preferred_bike(db=db, user_id=current_user.user_id, bike_id=bike_id)


@garage_router.post(
    "/{bike_id}/photos/upload-intent",
    response_model=BikePhotoUploadIntentOut,
    summary="Request Bike Photo Upload Intent",
    description=(
        "M03 - Motorcycle Garage. Validates JPEG/PNG/WebP, up to 5 MB, maximum 5 photos per bike."
    ),
    openapi_extra={"module_code": "M03"},
)
async def api_bike_photo_intent(
    bike_id: uuid.UUID,
    payload: BikePhotoUploadIntentIn,
    current_user: AuthenticatedUser = Depends(require_module_code("M03")),
    db: AsyncSession = Depends(get_db),
) -> BikePhotoUploadIntentOut:
    return await create_bike_photo_intent(
        db=db,
        user_id=current_user.user_id,
        bike_id=bike_id,
        payload=payload,
    )


@garage_router.post(
    "/{bike_id}/photos/complete",
    response_model=BikeOut,
    summary="Complete Bike Photo Upload",
    description="M03 - Motorcycle Garage. Unavailable until safety scan state is clean.",
    openapi_extra={"module_code": "M03"},
)
async def api_complete_bike_photo(
    bike_id: uuid.UUID,
    payload: BikePhotoCompleteIn,
    current_user: AuthenticatedUser = Depends(require_module_code("M03")),
    db: AsyncSession = Depends(get_db),
) -> BikeOut:
    return await complete_bike_photo(
        db=db,
        user_id=current_user.user_id,
        bike_id=bike_id,
        payload=payload,
    )


# ==============================================================================
# M21: Maintenance Records & Documents
# ==============================================================================


@garage_router.get(
    "/{bike_id}/maintenance",
    response_model=List[MaintenanceRecordOut],
    summary="List Maintenance Records",
    description="M21 - Maintenance & Service Reminders. Rider app only.",
    openapi_extra={"module_code": "M21"},
)
async def api_list_maintenance(
    bike_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_module_code("M21")),
    db: AsyncSession = Depends(get_db),
) -> List[MaintenanceRecordOut]:
    return await list_maintenance_records(db=db, user_id=current_user.user_id, bike_id=bike_id)


@garage_router.post(
    "/{bike_id}/maintenance",
    response_model=MaintenanceRecordOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add Maintenance Record",
    description=(
        "M21 - Maintenance & Service Reminders. Updates bike odometer if new reading is higher."
    ),
    openapi_extra={"module_code": "M21"},
)
async def api_create_maintenance(
    bike_id: uuid.UUID,
    payload: MaintenanceRecordIn,
    current_user: AuthenticatedUser = Depends(require_module_code("M21")),
    db: AsyncSession = Depends(get_db),
) -> MaintenanceRecordOut:
    return await create_maintenance_record(
        db=db,
        user_id=current_user.user_id,
        bike_id=bike_id,
        payload=payload,
    )


@garage_router.post(
    "/{bike_id}/maintenance/upload-intent",
    response_model=MediaUploadIntentOut,
    summary="Request Maintenance Invoice Upload Intent",
    description=(
        "M21 - Maintenance & Service Reminders. Signed upload URL for invoice PDF or image."
    ),
    openapi_extra={"module_code": "M21"},
)
async def api_maintenance_file_intent(
    bike_id: uuid.UUID,
    payload: MediaUploadIntentIn,
    current_user: AuthenticatedUser = Depends(require_module_code("M21")),
    db: AsyncSession = Depends(get_db),
) -> MediaUploadIntentOut:
    return await create_bike_file_intent(
        db=db,
        user_id=current_user.user_id,
        bike_id=bike_id,
        purpose="maintenance_invoice",
        payload=payload,
    )


@garage_router.post(
    "/{bike_id}/maintenance/upload-complete",
    summary="Complete Maintenance Invoice Upload",
    description="M21 - Maintenance & Service Reminders.",
    openapi_extra={"module_code": "M21"},
)
async def api_maintenance_file_complete(
    bike_id: uuid.UUID,
    payload: MediaCompleteIn,
    current_user: AuthenticatedUser = Depends(require_module_code("M21")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await complete_bike_file(
        db=db,
        user_id=current_user.user_id,
        bike_id=bike_id,
        payload=payload,
    )


@garage_router.get(
    "/{bike_id}/documents",
    response_model=List[BikeDocumentOut],
    summary="List Bike Documents",
    description=(
        "M21 - Maintenance & Service Reminders. Private access with short-lived download URLs."
    ),
    openapi_extra={"module_code": "M21"},
)
async def api_list_documents(
    bike_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_module_code("M21")),
    db: AsyncSession = Depends(get_db),
) -> List[BikeDocumentOut]:
    return await list_bike_documents(db=db, user_id=current_user.user_id, bike_id=bike_id)


@garage_router.post(
    "/{bike_id}/documents",
    response_model=BikeDocumentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add Bike Document",
    description=(
        "M21 - Maintenance & Service Reminders. "
        "Records legal document with short-lived signed access."
    ),
    openapi_extra={"module_code": "M21"},
)
async def api_create_document(
    bike_id: uuid.UUID,
    payload: BikeDocumentIn,
    current_user: AuthenticatedUser = Depends(require_module_code("M21")),
    db: AsyncSession = Depends(get_db),
) -> BikeDocumentOut:
    return await create_bike_document(
        db=db,
        user_id=current_user.user_id,
        bike_id=bike_id,
        payload=payload,
    )


@garage_router.post(
    "/{bike_id}/documents/upload-intent",
    response_model=MediaUploadIntentOut,
    summary="Request Bike Document Upload Intent",
    description="M21 - Maintenance & Service Reminders. Signed upload URL for legal document.",
    openapi_extra={"module_code": "M21"},
)
async def api_document_file_intent(
    bike_id: uuid.UUID,
    payload: MediaUploadIntentIn,
    current_user: AuthenticatedUser = Depends(require_module_code("M21")),
    db: AsyncSession = Depends(get_db),
) -> MediaUploadIntentOut:
    return await create_bike_file_intent(
        db=db,
        user_id=current_user.user_id,
        bike_id=bike_id,
        purpose="bike_document",
        payload=payload,
    )


@garage_router.post(
    "/{bike_id}/documents/upload-complete",
    summary="Complete Bike Document Upload",
    description="M21 - Maintenance & Service Reminders.",
    openapi_extra={"module_code": "M21"},
)
async def api_document_file_complete(
    bike_id: uuid.UUID,
    payload: MediaCompleteIn,
    current_user: AuthenticatedUser = Depends(require_module_code("M21")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await complete_bike_file(
        db=db,
        user_id=current_user.user_id,
        bike_id=bike_id,
        payload=payload,
    )
