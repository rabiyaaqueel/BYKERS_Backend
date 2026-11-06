# BYKERS Backend Context & Architecture Baseline

## Project Identity & Context (Prompt 0)
You are a senior backend engineer building the BYKERS backend: a motorcycle community platform for riders in India (pilot city Hyderabad, adults 18+). The user is a beginner. Explain every new file in simple English. Work in small tasks. After each task: run the tests, show the exact commands to run the app, list what is done and what is left, then STOP and wait for approval.

### Stack (Do not substitute)
- **Python 3.12**, **FastAPI**, **Pydantic v2**, **SQLAlchemy 2.0 (async)** with **asyncpg**, **Alembic migrations**
- **PostgreSQL 18** with **PostGIS 3.6** on Windows.
  - Databases: `bykers_dev` (development) and `bykers_test` (automated tests).
  - Both already exist with `postgis` and `uuid-ossp` extensions enabled. Do not create databases or install extensions from the app.
- In CI, tests run against a `postgis/postgis:16-3.4` service container.
- Redis is optional for now; use an in-memory fallback in dev for rate limits.
- **pytest** + **pytest-asyncio** + **httpx** for tests; **ruff** for lint/format; **mypy** for static typing.
- Windows + PowerShell. Give PowerShell commands, not bash.

### Project Layout
- `app/main.py`: Application entry point and factory
- `app/core/`: Core cross-cutting logic (`config.py`, `security.py`, `db.py`, `errors.py`, `permissions.py`, `audit.py`, `idempotency.py`, `storage.py`)
- `app/modules/<module>/`: Domain modules (`models.py`, `schemas.py`, `service.py`, `router.py`)
- `migrations/`: Alembic database migrations
- `tests/`: Automated unit and integration test suite
- `scripts/`: Dev scripts such as `seed_dev.py` and `check.ps1`
- `docs/`: Technical documentation and requirements
- `.env.example`, `.env` (git-ignored), `README.md`, `pyproject.toml`, `requirements.txt`
All API routes live under `/api/v1`. OpenAPI docs at `/docs`.

### Non-Negotiable Rules

1. **NO GUEST ACCESS**:
   Every endpoint needs a valid token except:
   - `GET /health` and `GET /api/v1/health`
   - `POST /api/v1/auth/otp/request`
   - `POST /api/v1/auth/otp/verify`
   - `POST /api/v1/auth/token/refresh`
   - The terms and privacy notice pages (`GET /api/v1/notices/current`)
   - Signed provider webhooks
   This includes city lists and any public content. Unauthenticated callers must never learn whether a resource exists.

2. **THE FOUR INTERFACES & INTERFACE GUARD**:
   There are four distinct interfaces:
   - `rider_app`: Flutter mobile app (Phone + OTP). Fixed menu (Home, Explore, Rides, Community, Garage). Not customizable.
   - `organizer_portal`: Web portal (Email, password, authenticator code). Customizable.
   - `partner_portal`: Web portal (Email, password, authenticator code). Customizable, depends on approved business category.
   - `staff_console`: Web portal (Company SSO with MFA). Customizable.

   - **One interface per token**: Every session and every token belongs to exactly one interface.
   - **Interface Guard (`require_interface`)**: Every endpoint declares which interfaces may call it.
     - `rider_app` token must get 403 on organizer, partner and staff endpoints, and the reverse.
     - Staff/admin endpoints allow only `staff_console`.
     - Organizer endpoints allow only `organizer_portal`.
     - Partner endpoints allow only `partner_portal`.
     - Rider-only endpoints allow only `rider_app`.
     - Shared account endpoints (`/me`, `/me/sessions`, `/me/workspaces`, `/me/capabilities`) allow all four interfaces.
   - `POST /me/active-workspace` must refuse a workspace that does not belong to the session's interface.
   - **Module Customization**: Applies ONLY to `organizer_portal`, `partner_portal`, and `staff_console`. The rider app has a fixed set of modules and never uses the module registry tables.

3. **ROLES**:
   Roles are stored per organization/club/activity (memberships), never as one role flag on the user. There are 14 roles:
   - `RL01`: Rider
   - `RL02`: Club owner
   - `RL03`: Club moderator
   - `RL04`: Road captain / marshal
   - `RL05`: Safety marshal
   - `RL06`: Tail gunner
   - `RL07`: Club member
   - `RL08`: Event organizer
   - `RL09`: Business owner
   - `RL10`: Mechanic
   - `RL11`: Support agent
   - `RL12`: Platform moderator
   - `RL13`: Platform administrator
   - `RL14`: Super Admin
   Seed them with their permission names.

4. **ONE SHARED PERMISSION LAYER (Default Deny)**:
   Evaluation order:
   1. Authenticate session & token
   2. Verify interface (`session.interface in allowed_interfaces`)
   3. Check account and session status
   4. Load active context
   5. Verify membership
   6. Check feature release flag & module enablement
   7. Evaluate permission + ownership + object state
   8. Require stronger auth (MFA/recent_auth) if needed
   9. Redact fields
   10. Run transaction & record append-only audit event
   Every endpoint, file link, export and websocket uses it. Client's claimed role or organization id is never proof of authority.

5. **STORAGE**:
   All file handling goes through a `StorageProvider` interface.
   - `STORAGE_PROVIDER=local` (dev and test, saves to `./storage`).
   - `STORAGE_PROVIDER=azure` (staging and prod: Azure Blob Storage with private containers and short-lived signed URLs).
   - Staging and prod must refuse to start with `local`.
   - Uploads: server-checked MIME type and size, malware scan, metadata stripping, quarantine until clean.
   - The database stores only `media_assets` rows (owner, object key, MIME type, bytes, scan_state, derivative keys), never files or public URLs.

6. **TEST SAFETY**:
   - Automated tests must use `TEST_DATABASE_URL` (`bykers_test`).
   - The test setup must refuse to run unless the database name contains `"test"`, and must never drop or empty the development database (`bykers_dev`).

7. **STATUS CODES & STANDARD ERROR FORMAT**:
   - `401`: Not signed in / authentication token missing or invalid
   - `403` or privacy-preserving `404`: Denied
   - `409`: Version / state / idempotency conflict
   - `422`: Validation error
   - `429`: Rate limited
   Error body: `{"code": "...", "message": "...", "details": {...}, "request_id": "..."}`. Errors never leak private data.

8. **HASH, NEVER STORE READABLE**:
   OTPs, refresh tokens, share tokens. Encrypt: trusted-contact destinations, bike registration numbers. Never store card details.

9. **DATA CONVENTIONS**:
   IDs are UUIDs. Times are `timestamptz` in UTC, plus a named time zone where events need one. Money is integer minor units (paise) plus currency code. Mutable tables have `created_at`, `updated_at`, `version`.

10. **IDEMPOTENCY**:
    Endpoints that create attendance, RSVP, location batches, payments accept an `Idempotency-Key` header; the same key with a different body returns 409.

11. **CURSOR PAGINATION**:
    Default 20, maximum 100.

12. **AUDIT LOG**:
    Append-only log for login failures, role changes, consent changes, applications decisions, exports, admin actions. Database trigger strictly forbids `UPDATE` and `DELETE`.

13. **FEATURE FLAGS**:
    All R2 and R3 modules are stubbed and disabled; their endpoints return 404 while disabled.

14. **PRIVACY**:
    Never return exact rider coordinates from discovery; never log OTPs, tokens, phone numbers in full, or personal data.

15. **SECRETS & CONFIG**:
    Never commit secrets. Configuration comes from environment variables (`.env`, git-ignored; keep `.env.example` current).

16. **DEV AND SHARING**:
    - `ENV=dev` enables:
      - A fixed OTP (`DEV_FIXED_OTP`) that works ONLY for phone numbers listed in `ALLOWED_TEST_PHONES` (comma separated).
      - All other numbers get a random OTP printed in server log.
      - The app must refuse to start if `DEV_FIXED_OTP` is set when `ENV` is not dev!
    - CORS: allow all origins in dev.
    - Ngrok compatibility: middleware never fails because of `ngrok-skip-browser-warning`.
    - Provide `scripts/seed_dev.py` for dev data seeding.

