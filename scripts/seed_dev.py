"""Development Data Seeding Script.

Creates dev baseline data (only when ENV=dev):
- Test riders
- Club owner, moderator, ride captain
- Platform administrator
- Sample club organization with memberships
- Platform organization with admin membership
Prints all test phone numbers and login OTP.
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.permissions import RoleCode
from app.modules.auth.models import AuthIdentity, User, UserStatus
from app.modules.authz.models import (
    ClubMembership,
    MembershipStatus,
    Organization,
    OrganizationMembership,
    OrganizationType,
    OrgApprovalState,
    Role,
)


async def seed() -> None:
    if settings.ENV != "dev":
        print(f"[BYKERS] Seeding is only permitted in ENV=dev. Current ENV={settings.ENV}")
        return

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    print("\n==================================================")
    print("           BYKERS Dev Data Seeding                ")
    print("==================================================")

    async with session_factory() as db:
        # 1. Fetch Roles
        stmt_roles = select(Role)
        res_roles = await db.execute(stmt_roles)
        roles_map = {r.code: r for r in res_roles.scalars().all()}

        if not roles_map:
            print("[ERROR] Roles table is empty! Run alembic upgrade head first.")
            return

        # Helper to get or create user
        async def get_or_create_user(phone: str, status: str = UserStatus.ACTIVE.value) -> User:
            stmt = select(User).where(User.phone_normalized == phone)
            user = (await db.execute(stmt)).scalar_one_or_none()
            if not user:
                user = User(
                    phone_normalized=phone,
                    status=status,
                    phone_verified_at=datetime.now(timezone.utc),
                    locale="en-IN",
                )
                db.add(user)
                await db.flush()

                # Add auth identity
                ident = AuthIdentity(
                    user_id=user.id,
                    provider="phone",
                    subject=phone,
                    verified_at=datetime.now(timezone.utc),
                )
                db.add(ident)
                await db.flush()
            return user

        # 2. Seed Test Riders
        rider_phones = ["+919876543210", "+919876543211", "+919876543212"]
        riders = []
        for p in rider_phones:
            r = await get_or_create_user(p)
            riders.append(r)

        # 3. Seed Club Owner, Moderator, Captain
        club_owner = await get_or_create_user("+919876543220")
        club_mod = await get_or_create_user("+919876543221")
        club_cap = await get_or_create_user("+919876543222")

        # 4. Seed Platform Admin
        admin_user = await get_or_create_user("+919876543230")

        # 4b. Seed Partner Owner
        partner_owner = await get_or_create_user("+919876543240")

        # 5. Seed Sample Motorcycle Club Organization
        club_name = "Hyderabad Falcon Riders Club"
        stmt_club = select(Organization).where(Organization.name == club_name)
        sample_club = (await db.execute(stmt_club)).scalar_one_or_none()

        if not sample_club:
            sample_club = Organization(
                type=OrganizationType.CLUB_ORG.value,
                name=club_name,
                approval_state=OrgApprovalState.APPROVED.value,
                created_by=club_owner.id,
            )
            db.add(sample_club)
            await db.flush()

        # Helper to ensure membership
        async def ensure_membership(u_id: uuid.UUID, org_id: uuid.UUID, role_code: str) -> None:
            r = roles_map.get(role_code)
            if not r:
                return
            stmt = select(OrganizationMembership).where(
                OrganizationMembership.user_id == u_id,
                OrganizationMembership.organization_id == org_id,
                OrganizationMembership.role_id == r.id,
            )
            mem = (await db.execute(stmt)).scalar_one_or_none()
            if not mem:
                mem = OrganizationMembership(
                    user_id=u_id,
                    organization_id=org_id,
                    role_id=r.id,
                    status=MembershipStatus.ACTIVE.value,
                    version=1,
                )
                db.add(mem)

        # Assign Club Memberships
        await ensure_membership(club_owner.id, sample_club.id, RoleCode.RL02_CLUB_OWNER.value)
        await ensure_membership(club_mod.id, sample_club.id, RoleCode.RL03_CLUB_MODERATOR.value)
        await ensure_membership(
            club_cap.id, sample_club.id, RoleCode.RL04_RIDE_CAPTAIN_MARSHAL.value
        )

        # Ensure ClubMembership for owner
        stmt_cm = select(ClubMembership).where(
            ClubMembership.club_id == sample_club.id,
            ClubMembership.user_id == club_owner.id,
        )
        if not (await db.execute(stmt_cm)).scalar_one_or_none():
            db.add(
                ClubMembership(
                    club_id=sample_club.id,
                    user_id=club_owner.id,
                    role="owner",
                    status=MembershipStatus.ACTIVE.value,
                    version=1,
                )
            )

        # 5b. Seed Sample Partner Business Organization
        partner_name = "Highway 44 Biker Cafe & Pitstop"
        stmt_partner = select(Organization).where(Organization.name == partner_name)
        sample_partner = (await db.execute(stmt_partner)).scalar_one_or_none()

        if not sample_partner:
            sample_partner = Organization(
                type=OrganizationType.BUSINESS.value,
                name=partner_name,
                approval_state=OrgApprovalState.APPROVED.value,
                created_by=partner_owner.id,
            )
            db.add(sample_partner)
            await db.flush()

        await ensure_membership(
            partner_owner.id, sample_partner.id, RoleCode.RL07_PARTNER_OWNER.value
        )

        # Seed approved partner category
        from app.modules.registry.models import (
            CategoryApprovalState,
            OrganizationCategory,
        )

        stmt_oc = select(OrganizationCategory).where(
            OrganizationCategory.organization_id == sample_partner.id,
            OrganizationCategory.category == "cafe",
        )
        if not (await db.execute(stmt_oc)).scalar_one_or_none():
            db.add(
                OrganizationCategory(
                    organization_id=sample_partner.id,
                    category="cafe",
                    approval_state=CategoryApprovalState.APPROVED.value,
                    approved_by=admin_user.id,
                    approved_at=datetime.now(timezone.utc),
                )
            )

        # 6. Seed Platform Governance Organization & Admin Membership
        stmt_plat = select(Organization).where(Organization.type == OrganizationType.PLATFORM.value)
        plat_org = (await db.execute(stmt_plat)).scalar_one_or_none()

        if not plat_org:
            plat_org = Organization(
                type=OrganizationType.PLATFORM.value,
                name="BYKERS Platform Administration",
                approval_state=OrgApprovalState.APPROVED.value,
                created_by=admin_user.id,
            )
            db.add(plat_org)
            await db.flush()

        await ensure_membership(admin_user.id, plat_org.id, RoleCode.RL13_PLATFORM_ADMIN.value)

        await db.commit()

        print("[SUCCESS] Dev data seeded successfully!")
        print("\nTest Accounts Available (Fixed OTP: 123456):")
        print("  - Test Rider 1:       +919876543210 (Personal Workspace)")
        print("  - Test Rider 2:       +919876543211 (Personal Workspace)")
        print("  - Test Rider 3:       +919876543212 (Personal Workspace)")
        print(f"  - Club Owner:         +919876543220 (Club Workspace: {sample_club.name})")
        print(f"  - Club Moderator:     +919876543221 (Club Workspace: {sample_club.name})")
        print(f"  - Ride Captain:       +919876543222 (Club Workspace: {sample_club.name})")
        print("  - Platform Admin:     +919876543230 (Staff Workspace & Audit Access)")
        print(f"  - Partner Owner:      +919876543240 (Partner Workspace: {sample_partner.name})")
        print("==================================================\n")

    await engine.dispose()


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
