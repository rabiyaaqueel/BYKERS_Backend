"""API Router for Rider Onboarding, Profiles, Consents, and Metadata."""

import uuid
from typing import List

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.dependencies import (
    AuthenticatedUser,
    get_client_ip,
    get_user_agent,
    require_interface,
)
from app.modules.rider.schemas import (
    AcceptNoticesIn,
    AccountSetupIn,
    CityOut,
    ConsentEventOut,
    ConsentUpdateIn,
    ExtendedMeOut,
    InterestOut,
    NoticeCurrentOut,
    PhotoCompleteIn,
    PhotoCompleteOut,
    PhotoUploadIntentIn,
    PhotoUploadIntentOut,
    ProfilePatchIn,
    PublicProfileOut,
)
from app.modules.rider.service import (
    accept_updated_notices,
    complete_photo_upload,
    create_photo_upload_intent,
    get_active_cities,
    get_active_interests,
    get_current_notices,
    get_rider_consents,
    get_rider_public_profile,
    patch_rider_profile,
    setup_rider_account,
    update_rider_consent,
)

meta_router = APIRouter(prefix="/meta", tags=["Metadata"])
notices_router = APIRouter(prefix="/notices", tags=["Legal Notices"])
rider_me_router = APIRouter(prefix="/me", tags=["Rider Profile & Consents"])
profiles_router = APIRouter(prefix="/profiles", tags=["Profiles"])


# --- Public Notices ---
@notices_router.get(
    "/current",
    response_model=NoticeCurrentOut,
    summary="Get Current Legal Notices",
    description="Public endpoint returning current active versions of Terms and Privacy Policy.",
)
async def api_get_current_notices(
    db: AsyncSession = Depends(get_db),
) -> NoticeCurrentOut:
    return await get_current_notices(db)


# --- Metadata (Cities & Interests) ---
@meta_router.get(
    "/cities",
    response_model=List[CityOut],
    summary="List Supported Cities",
    description="Returns active motorcycle hub cities. Requires rider login.",
)
async def api_list_cities(
    current_user: AuthenticatedUser = Depends(require_interface("rider_app")),
    db: AsyncSession = Depends(get_db),
) -> List[CityOut]:
    return await get_active_cities(db)


@meta_router.get(
    "/interests",
    response_model=List[InterestOut],
    summary="List Rider Interests",
    description="Returns available riding interests with English, Telugu, and Hindi translations.",
)
async def api_list_interests(
    current_user: AuthenticatedUser = Depends(require_interface("rider_app")),
    db: AsyncSession = Depends(get_db),
) -> List[InterestOut]:
    return await get_active_interests(db)


# --- Account Setup & Profile ---
@rider_me_router.post(
    "/account-setup",
    response_model=ExtendedMeOut,
    summary="Complete Rider Account Setup",
    description=(
        "Validates adult declaration, checks legal notices, saves consents, "
        "and initializes rider profile."
    ),
)
async def api_account_setup(
    payload: AccountSetupIn,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_interface("rider_app")),
    db: AsyncSession = Depends(get_db),
) -> ExtendedMeOut:
    ip = get_client_ip(request)
    ua = get_user_agent(request)
    return await setup_rider_account(db, current_user.user_id, payload, ip=ip, user_agent=ua)


@rider_me_router.post(
    "/accept-notices",
    response_model=ExtendedMeOut,
    summary="Accept Updated Legal Notices",
    description="Records consent when Terms of Service or Privacy Policy notice versions change.",
)
async def api_accept_notices(
    payload: AcceptNoticesIn,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_interface("rider_app")),
    db: AsyncSession = Depends(get_db),
) -> ExtendedMeOut:
    ip = get_client_ip(request)
    ua = get_user_agent(request)
    return await accept_updated_notices(db, current_user.user_id, payload, ip=ip, user_agent=ua)


@rider_me_router.patch(
    "",
    response_model=ExtendedMeOut,
    summary="Update Own Profile",
    description=(
        "Allows authenticated riders to edit their display name, bio, experience, "
        "visibility, and private details."
    ),
)
async def api_patch_profile(
    payload: ProfilePatchIn,
    current_user: AuthenticatedUser = Depends(require_interface("rider_app")),
    db: AsyncSession = Depends(get_db),
) -> ExtendedMeOut:
    return await patch_rider_profile(db, current_user.user_id, payload)


@rider_me_router.get(
    "/profile-preview",
    response_model=PublicProfileOut,
    summary="Preview Own Public Profile",
    description="Returns the profile exactly as visible to other riders.",
)
async def api_profile_preview(
    current_user: AuthenticatedUser = Depends(require_interface("rider_app")),
    db: AsyncSession = Depends(get_db),
) -> PublicProfileOut:
    return await get_rider_public_profile(db, current_user.user_id, current_user.user_id)


# --- Consents ---
@rider_me_router.get(
    "/consents",
    response_model=List[ConsentEventOut],
    summary="Get Consent History",
    description="Returns the complete append-only history of consent events for the caller.",
)
async def api_get_consents(
    current_user: AuthenticatedUser = Depends(require_interface("rider_app")),
    db: AsyncSession = Depends(get_db),
) -> List[ConsentEventOut]:
    return await get_rider_consents(db, current_user.user_id)


@rider_me_router.post(
    "/consents",
    response_model=ConsentEventOut,
    summary="Update Consent Preference",
    description=(
        "Grants or withdraws consent for specific purposes (marketing, location, etc.). "
        "Appends immediately."
    ),
)
async def api_update_consent(
    payload: ConsentUpdateIn,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_interface("rider_app")),
    db: AsyncSession = Depends(get_db),
) -> ConsentEventOut:
    ip = get_client_ip(request)
    ua = get_user_agent(request)
    return await update_rider_consent(db, current_user.user_id, payload, ip=ip, user_agent=ua)


# --- Photo Upload ---
@rider_me_router.post(
    "/photo/upload-intent",
    response_model=PhotoUploadIntentOut,
    summary="Request Avatar Upload Intent",
    description=(
        "Validates image MIME type and file size (max 5 MB) and returns signed storage upload URL."
    ),
)
async def api_photo_upload_intent(
    payload: PhotoUploadIntentIn,
    current_user: AuthenticatedUser = Depends(require_interface("rider_app")),
    db: AsyncSession = Depends(get_db),
) -> PhotoUploadIntentOut:
    return await create_photo_upload_intent(db, current_user.user_id, payload)


@rider_me_router.post(
    "/photo/complete",
    response_model=PhotoCompleteOut,
    summary="Complete Avatar Upload",
    description=(
        "Validates ownership and scan state of the uploaded photo and links it to rider profile."
    ),
)
async def api_photo_complete(
    payload: PhotoCompleteIn,
    current_user: AuthenticatedUser = Depends(require_interface("rider_app")),
    db: AsyncSession = Depends(get_db),
) -> PhotoCompleteOut:
    return await complete_photo_upload(db, current_user.user_id, payload)


# --- Public Profiles ---
@profiles_router.get(
    "/{user_id}",
    response_model=PublicProfileOut,
    summary="View Rider Public Profile",
    description=(
        "Returns public profile fields respecting visibility. NEVER returns legal name, "
        "email, or phone."
    ),
)
async def api_get_public_profile(
    user_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_interface("rider_app")),
    db: AsyncSession = Depends(get_db),
) -> PublicProfileOut:
    return await get_rider_public_profile(db, user_id, current_user.user_id)
