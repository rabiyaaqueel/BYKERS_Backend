"""Development Data Seeding Script (Placeholder for Task A, fully populated in Auth/Users tasks).

Only runs when ENV=dev.
"""

from app.core.config import settings


def main() -> None:
    if settings.ENV != "dev":
        print(f"[BYKERS] Seeding is only permitted in ENV=dev. Current ENV={settings.ENV}")
        return

    print("=== BYKERS Dev Seed Script ===")
    print(f"Allowed Dev Test Phones ({len(settings.ALLOWED_TEST_PHONES)} configured):")
    for phone in settings.ALLOWED_TEST_PHONES:
        print(f"  - {phone} (Fixed Dev OTP: {settings.DEV_FIXED_OTP})")
    print("Dev seed script initialized.")


if __name__ == "__main__":
    main()
