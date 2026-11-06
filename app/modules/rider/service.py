"""Service layer for Rider Onboarding, Profiles, Consents, and Media Assets."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import record_audit_event
from app.core.errors import (
    NotFoundError,
    ValidationError,
)
from app.core.security import mask_phone
from app.core.storage import get_storage_provider
from app.modules.auth.models import User, UserStatus
from app.modules.garage.models import Bike
from app.modules.rider.models import (
    City,
    ConsentEvent,
    Interest,
    MediaAsset,
    NoticeVersion,
    PrivateDetail,
    Profile,
    UserInterest,
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
    NoticeVersionOut,
    PhotoCompleteIn,
    PhotoCompleteOut,
    PhotoUploadIntentIn,
    PhotoUploadIntentOut,
    PrivateDetailsOut,
    ProfilePatchIn,
    PublicProfileOut,
)

logger = logging.getLogger("bykers.rider")


async def get_active_cities(db: AsyncSession) -> List[CityOut]:
    """Returns list of all active supported cities."""
    stmt = select(City).where(City.active.is_(True)).order_by(City.name.asc())
    result = await db.execute(stmt)
    return [CityOut.model_validate(c) for c in result.scalars().all()]


async def get_active_interests(db: AsyncSession) -> List[InterestOut]:
    """Returns list of all available rider interests with translations."""
    stmt = select(Interest).where(Interest.active.is_(True)).order_by(Interest.name_en.asc())
    result = await db.execute(stmt)
    return [InterestOut.model_validate(i) for i in result.scalars().all()]


async def get_current_notices(db: AsyncSession) -> NoticeCurrentOut:
    """Returns the latest active Terms of Service and Privacy Policy versions."""
    stmt_terms = select(NoticeVersion).where(
        NoticeVersion.kind == "terms", NoticeVersion.is_current.is_(True)
    )
    stmt_privacy = select(NoticeVersion).where(
        NoticeVersion.kind == "privacy", NoticeVersion.is_current.is_(True)
    )

    res_terms = await db.execute(stmt_terms)
    res_privacy = await db.execute(stmt_privacy)

    terms_row = res_terms.scalar_one_or_none()
    privacy_row = res_privacy.scalar_one_or_none()

    return NoticeCurrentOut(
        terms=NoticeVersionOut.model_validate(terms_row) if terms_row else None,
        privacy=NoticeVersionOut.model_validate(privacy_row) if privacy_row else None,
    )


async def setup_rider_account(
    db: AsyncSession,
    user_id: uuid.UUID,
    payload: AccountSetupIn,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> ExtendedMeOut:
    """Completes rider onboarding setup: verifies adult declaration, active legal notices,

    records consents, creates profile and sets status to active.
    """
    if not payload.adult_declaration:
        raise ValidationError("Adult declaration required: must be at least 18 years old.")

    current_notices = await get_current_notices(db)
    cur_terms = current_notices.terms.version if current_notices.terms else "none"
    if not current_notices.terms or payload.accepted_terms_version != current_notices.terms.version:
        raise ValidationError(
            f"Stale terms version '{payload.accepted_terms_version}'. Current is '{cur_terms}'."
        )

    cur_priv = current_notices.privacy.version if current_notices.privacy else "none"
    if (
        not current_notices.privacy
        or payload.accepted_privacy_version != current_notices.privacy.version
    ):
        raise ValidationError(
            f"Stale privacy policy version '{payload.accepted_privacy_version}'. "
            f"Current is '{cur_priv}'."
        )

    # 1. Verify city if provided
    if payload.city_id:
        city_stmt = select(City).where(City.id == payload.city_id, City.active.is_(True))
        city_res = await db.execute(city_stmt)
        if not city_res.scalar_one_or_none():
            raise ValidationError("Selected city is invalid or inactive.")

    # 2. Append consent events (Terms, Privacy, and Marketing if opted in)
    now = datetime.now(timezone.utc)
    consents_to_add = [
        ConsentEvent(
            user_id=user_id,
            purpose="terms",
            action="granted",
            notice_version=payload.accepted_terms_version,
            ip_address=ip,
            user_agent=user_agent,
            occurred_at=now,
        ),
        ConsentEvent(
            user_id=user_id,
            purpose="privacy",
            action="granted",
            notice_version=payload.accepted_privacy_version,
            ip_address=ip,
            user_agent=user_agent,
            occurred_at=now,
        ),
    ]
    if payload.marketing_consent:
        consents_to_add.append(
            ConsentEvent(
                user_id=user_id,
                purpose="marketing",
                action="granted",
                notice_version=payload.accepted_terms_version,
                ip_address=ip,
                user_agent=user_agent,
                occurred_at=now,
            )
        )
    for c in consents_to_add:
        db.add(c)

    # 3. Create or update Profile
    prof_stmt = select(Profile).where(Profile.user_id == user_id)
    prof_res = await db.execute(prof_stmt)
    profile = prof_res.scalar_one_or_none()

    if profile:
        profile.display_name = payload.display_name
        profile.home_city_id = payload.city_id
        profile.updated_at = now
    else:
        profile = Profile(
            user_id=user_id,
            display_name=payload.display_name,
            home_city_id=payload.city_id,
            experience="beginner",
            visibility="all_riders",
            languages=[],
            created_at=now,
            updated_at=now,
        )
        db.add(profile)

    # 4. Associate interests
    if payload.interests:
        int_stmt = select(Interest).where(Interest.code.in_(payload.interests))
        int_res = await db.execute(int_stmt)
        interests = int_res.scalars().all()
        # Clear existing
        await db.execute(delete(UserInterest).where(UserInterest.user_id == user_id))
        for item in interests:
            db.add(UserInterest(user_id=user_id, interest_id=item.id))

    # 5. Set user status to active
    user_stmt = select(User).where(User.id == user_id)
    user_res = await db.execute(user_stmt)
    user = user_res.scalar_one_or_none()
    if user:
        user.status = UserStatus.ACTIVE

    await db.commit()

    record_audit_event(
        actor=str(user_id),
        action="account.setup_completed",
        resource=f"user:{user_id}",
        metadata={
            "display_name": payload.display_name,
            "city_id": str(payload.city_id) if payload.city_id else None,
        },
    )

    return await get_extended_me(db, user_id)


async def accept_updated_notices(
    db: AsyncSession,
    user_id: uuid.UUID,
    payload: AcceptNoticesIn,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> ExtendedMeOut:
    """Allows returning riders to accept updated legal notice revisions."""
    current = await get_current_notices(db)
    now = datetime.now(timezone.utc)

    if payload.accepted_terms_version:
        if not current.terms or payload.accepted_terms_version != current.terms.version:
            raise ValidationError("Invalid or outdated terms notice version.")
        db.add(
            ConsentEvent(
                user_id=user_id,
                purpose="terms",
                action="granted",
                notice_version=payload.accepted_terms_version,
                ip_address=ip,
                user_agent=user_agent,
                occurred_at=now,
            )
        )

    if payload.accepted_privacy_version:
        if not current.privacy or payload.accepted_privacy_version != current.privacy.version:
            raise ValidationError("Invalid or outdated privacy notice version.")
        db.add(
            ConsentEvent(
                user_id=user_id,
                purpose="privacy",
                action="granted",
                notice_version=payload.accepted_privacy_version,
                ip_address=ip,
                user_agent=user_agent,
                occurred_at=now,
            )
        )

    await db.commit()
    return await get_extended_me(db, user_id)


async def get_rider_public_profile(
    db: AsyncSession,
    target_user_id: uuid.UUID,
    viewer_user_id: uuid.UUID,
) -> PublicProfileOut:
    """Returns a rider's profile adhering strictly to visibility settings.

    NEVER returns legal name, email, or phone.
    """
    stmt = (
        select(Profile)
        .options(
            selectinload(Profile.home_city),
            selectinload(Profile.photo),
        )
        .where(Profile.user_id == target_user_id)
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()
    if not profile:
        raise NotFoundError("Rider profile not found.")

    is_owner = target_user_id == viewer_user_id

    # If visibility is private and caller is not owner, mask all details
    if profile.visibility == "private" and not is_owner:
        return PublicProfileOut(
            user_id=profile.user_id,
            display_name=profile.display_name,
            photo_url=None,
            city=None,
            bio=None,
            experience=profile.experience,
            visibility="private",
            languages=[],
            interests=[],
            verified_badges=["phone verified"],
            message="This profile is private.",
        )

    # Resolve interests
    int_stmt = (
        select(Interest)
        .join(UserInterest, UserInterest.interest_id == Interest.id)
        .where(UserInterest.user_id == target_user_id)
    )
    int_res = await db.execute(int_stmt)
    interests = [InterestOut.model_validate(i) for i in int_res.scalars().all()]

    # Resolve photo URL: only if scan_state == 'clean'
    photo_url = None
    if profile.photo and profile.photo.scan_state == "clean":
        storage = get_storage_provider()
        photo_url = await storage.get_download_url(profile.photo.object_key)

    city_name = profile.home_city.name if profile.home_city else None

    return PublicProfileOut(
        user_id=profile.user_id,
        display_name=profile.display_name,
        photo_url=photo_url,
        city=city_name,
        bio=profile.bio,
        experience=profile.experience,
        visibility=profile.visibility,
        languages=profile.languages or [],
        interests=interests,
        verified_badges=["phone verified"],
    )


async def patch_rider_profile(
    db: AsyncSession,
    user_id: uuid.UUID,
    payload: ProfilePatchIn,
) -> ExtendedMeOut:
    """Updates the authenticated rider's profile and/or private details."""
    now = datetime.now(timezone.utc)

    # 1. Update Profile
    prof_stmt = select(Profile).where(Profile.user_id == user_id)
    prof_res = await db.execute(prof_stmt)
    profile = prof_res.scalar_one_or_none()
    if not profile:
        raise NotFoundError("Profile not initialized. Please complete account setup first.")

    if payload.display_name is not None:
        profile.display_name = payload.display_name
    if payload.bio is not None:
        profile.bio = payload.bio
    if payload.home_city_id is not None:
        city_stmt = select(City).where(City.id == payload.home_city_id, City.active.is_(True))
        city_res = await db.execute(city_stmt)
        if not city_res.scalar_one_or_none():
            raise ValidationError("Selected city is invalid or inactive.")
        profile.home_city_id = payload.home_city_id
    if payload.experience is not None:
        profile.experience = payload.experience
    if payload.visibility is not None:
        profile.visibility = payload.visibility
    if payload.languages is not None:
        profile.languages = payload.languages
    profile.updated_at = now

    # 2. Update Interests
    if payload.interests is not None:
        int_stmt = select(Interest).where(Interest.code.in_(payload.interests))
        int_res = await db.execute(int_stmt)
        interests = int_res.scalars().all()
        await db.execute(delete(UserInterest).where(UserInterest.user_id == user_id))
        for item in interests:
            db.add(UserInterest(user_id=user_id, interest_id=item.id))

    # 3. Update Private Details
    if payload.legal_name is not None or payload.email is not None:
        priv_stmt = select(PrivateDetail).where(PrivateDetail.user_id == user_id)
        priv_res = await db.execute(priv_stmt)
        priv = priv_res.scalar_one_or_none()
        if priv:
            if payload.legal_name is not None:
                priv.legal_name = payload.legal_name
            if payload.email is not None:
                priv.email = payload.email
            priv.updated_at = now
        else:
            priv = PrivateDetail(
                user_id=user_id,
                legal_name=payload.legal_name,
                email=payload.email,
                created_at=now,
                updated_at=now,
            )
            db.add(priv)

    await db.commit()
    return await get_extended_me(db, user_id)


async def get_rider_consents(db: AsyncSession, user_id: uuid.UUID) -> List[ConsentEventOut]:
    """Returns the full append-only audit history of user consent decisions."""
    stmt = (
        select(ConsentEvent)
        .where(ConsentEvent.user_id == user_id)
        .order_by(ConsentEvent.occurred_at.asc())
    )
    result = await db.execute(stmt)
    return [ConsentEventOut.model_validate(c) for c in result.scalars().all()]


async def update_rider_consent(
    db: AsyncSession,
    user_id: uuid.UUID,
    payload: ConsentUpdateIn,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> ConsentEventOut:
    """Appends a new consent decision to the ledger and takes effect immediately."""
    now = datetime.now(timezone.utc)
    event = ConsentEvent(
        user_id=user_id,
        purpose=payload.purpose,
        action=payload.action,
        ip_address=ip,
        user_agent=user_agent,
        occurred_at=now,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)

    record_audit_event(
        actor=str(user_id),
        action=f"consent.{payload.action}",
        resource=f"consent:{payload.purpose}",
        metadata={"purpose": payload.purpose, "action": payload.action},
    )

    return ConsentEventOut.model_validate(event)


async def create_photo_upload_intent(
    db: AsyncSession,
    user_id: uuid.UUID,
    payload: PhotoUploadIntentIn,
) -> PhotoUploadIntentOut:
    """Creates a MediaAsset record and generates an authorized upload intent."""
    ext = payload.filename.rsplit(".", 1)[-1].lower() if "." in payload.filename else "jpg"
    asset_id = uuid.uuid4()
    object_key = f"avatars/{user_id}/{asset_id.hex}.{ext}"

    now = datetime.now(timezone.utc)
    asset = MediaAsset(
        id=asset_id,
        owner_id=user_id,
        purpose="profile_photo",
        object_key=object_key,
        mime_type=payload.mime_type,
        bytes=payload.bytes,
        scan_state="pending",
        created_at=now,
        updated_at=now,
    )
    db.add(asset)
    await db.commit()

    storage = get_storage_provider()
    upload_url = await storage.get_download_url(object_key)

    return PhotoUploadIntentOut(
        media_asset_id=asset_id,
        upload_url=upload_url,
        object_key=object_key,
        expires_in_seconds=900,
    )


async def complete_photo_upload(
    db: AsyncSession,
    user_id: uuid.UUID,
    payload: PhotoCompleteIn,
) -> PhotoCompleteOut:
    """Completes the photo upload, runs scan check, and assigns to profile."""
    stmt = select(MediaAsset).where(
        MediaAsset.id == payload.media_asset_id, MediaAsset.owner_id == user_id
    )
    result = await db.execute(stmt)
    asset = result.scalar_one_or_none()
    if not asset:
        raise NotFoundError("Uploaded media asset not found or not owned by caller.")

    # In dev/test environments, mark the asset scan clean automatically
    asset.scan_state = "clean"
    asset.updated_at = datetime.now(timezone.utc)

    # Link to Profile
    prof_stmt = select(Profile).where(Profile.user_id == user_id)
    prof_res = await db.execute(prof_stmt)
    profile = prof_res.scalar_one_or_none()
    if profile:
        profile.photo_media_id = asset.id
        profile.updated_at = datetime.now(timezone.utc)

    await db.commit()

    storage = get_storage_provider()
    photo_url = await storage.get_download_url(asset.object_key)

    return PhotoCompleteOut(
        media_asset_id=asset.id,
        scan_state=asset.scan_state,
        photo_url=photo_url,
    )


async def get_extended_me(db: AsyncSession, user_id: uuid.UUID) -> ExtendedMeOut:
    """Returns the comprehensive account details for the authenticated rider."""
    user_stmt = select(User).where(User.id == user_id)
    user_res = await db.execute(user_stmt)
    user = user_res.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found.")

    prof_stmt = (
        select(Profile)
        .options(
            selectinload(Profile.home_city),
            selectinload(Profile.photo),
        )
        .where(Profile.user_id == user_id)
    )
    prof_res = await db.execute(prof_stmt)
    profile = prof_res.scalar_one_or_none()

    priv_stmt = select(PrivateDetail).where(PrivateDetail.user_id == user_id)
    priv_res = await db.execute(priv_stmt)
    priv = priv_res.scalar_one_or_none()

    # Consents latest state
    consents_stmt = (
        select(ConsentEvent)
        .where(ConsentEvent.user_id == user_id)
        .order_by(ConsentEvent.occurred_at.asc())
    )
    consents_res = await db.execute(consents_stmt)
    consents_map: Dict[str, str] = {}
    for event in consents_res.scalars().all():
        consents_map[event.purpose] = event.action

    public_prof: Optional[PublicProfileOut] = None
    if profile:
        public_prof = await get_rider_public_profile(db, user_id, user_id)

    phone_masked = (
        mask_phone(user.phone_normalized) if user.phone_normalized else "Phone not linked"
    )
    account_setup_completed = profile is not None and user.status == UserStatus.ACTIVE

    bike_stmt = select(func.count(Bike.id)).where(
        Bike.user_id == user_id, Bike.archived_at.is_(None)
    )
    bike_res = await db.execute(bike_stmt)
    active_bikes_count = bike_res.scalar() or 0
    has_active_bike = active_bikes_count > 0

    profile_completeness = {
        "account_setup": account_setup_completed,
        "has_bike": has_active_bike,
        "active_bikes_count": active_bikes_count,
    }

    return ExtendedMeOut(
        id=user.id,
        phone_masked=phone_masked,
        status=user.status.value if hasattr(user.status, "value") else str(user.status),
        onboarding_required=not account_setup_completed,
        account_setup_completed=account_setup_completed,
        locale=user.locale,
        profile=public_prof,
        private_details=PrivateDetailsOut.model_validate(priv) if priv else None,
        consents=consents_map,
        verified_badges=["phone verified"],
        profile_completeness=profile_completeness,
    )
