"""Rider Onboarding, Profiles, and Consents Module."""

from app.modules.rider.router import (
    meta_router,
    notices_router,
    profiles_router,
    rider_me_router,
)

__all__ = [
    "meta_router",
    "notices_router",
    "rider_me_router",
    "profiles_router",
]
