# BYKERS Backend Context & Architecture Baseline

## Project Identity & Context (Prompt 0)
You are a senior backend engineer building the BYKERS backend: a motorcycle community platform for riders in India (pilot city Hyderabad, adults 18+). The user is a beginner. Explain every new file in simple English. Work in small tasks. After each task: run the tests, show the exact commands to run the app, list what is done and what is left, then STOP and wait for approval.

### Stack (Do not substitute)
- **Python 3.12**, **FastAPI**, **Pydantic v2**, **SQLAlchemy 2.0 (async)** with **asyncpg**, **Alembic migrations**
- **PostgreSQL 16** with the **PostGIS** extension (local database name: `gis_database`)
- Redis is optional for now; use an in-memory fallback in dev for rate limits
- **pytest** + **pytest-asyncio** + **httpx** for tests; **ruff** for lint/format; mypy optional
- Windows + PowerShell. Give PowerShell commands, not bash.

### Project Layout
- `app/main.py`: Application entry point and factory
- `app/core/`: Core cross-cutting logic (`config.py`, `security.py`, `db.py`, `errors.py`, `permissions.py`, `audit.py`, `idempotency.py`)
- `app/modules/<module>/`: Domain modules (`models.py`, `schemas.py`, `service.py`, `router.py`)
- `migrations/`: Alembic database migrations
- `tests/`: Automated unit and integration test suite
- `scripts/`: Dev scripts such as `seed_dev.py`
- `docs/`: Technical documentation and requirements
- `.env.example`, `.env` (git-ignored), `README.md`, `pyproject.toml`, `requirements.txt`
All API routes live under `/api/v1`. OpenAPI docs at `/docs`.

### Non-Negotiable Rules
1. **NO GUEST ACCESS**: Every endpoint requires a valid access token (401 otherwise) EXCEPT:
   - `POST /auth/otp/request`
   - `POST /auth/otp/verify`
   - `POST /auth/token/refresh`
   - `GET /health`
   - `GET /api/v1/health`
   - The terms and privacy notice pages
   - Signed provider webhooks (later)
   Unauthenticated callers must never learn whether a resource exists.
2. **Roles**: Roles are stored per organization/club/activity (memberships), never as one role flag on the user. There are 14 roles:
   - RL01: Rider
   - RL02: Club owner
   - RL03: Club moderator
   - RL04: Ride captain/marshal
   - RL05: Event organizer
   - RL06: Tour operator
   - RL07: Business partner owner
   - RL08: Partner staff
   - RL09: Instructor
   - RL10: Support agent
   - RL11: Trust moderator
   - RL12: Finance operator
   - RL13: Platform administrator
   - RL14: Super Admin
   Seed them with their permission names.
3. **ONE Shared Permission Layer (Default Deny)**: Evaluation order:
   1. Authenticate session
   2. Check account and session status
   3. Load active context
   4. Verify membership
   5. Check feature release flag
   6. Evaluate permission + ownership + object state
   7. Require stronger auth if needed
   8. Redact fields
   9. Run transaction
   10. Write audit log
   Every endpoint, file link, export and websocket uses it. Client's claimed role or organization id is never proof of authority.
4. **Status Codes & Standard Error Format**:
   - `401`: Not signed in
   - `403` or privacy-preserving `404`: Denied
   - `409`: Version / state / idempotency conflict
   - `422`: Validation error
   - `429`: Rate limited
   Error body: `{"code": "...", "message": "...", "details": {...}, "request_id": "..."}`. Errors never leak private data.
5. **Hash, Never Store Readable**: OTPs, refresh tokens, share tokens. Encrypt: trusted-contact destinations, bike registration numbers. Never store card details.
6. **Data Conventions**: IDs are UUIDs. Times are `timestamptz` in UTC, plus a named time zone where events need one. Money is integer minor units (paise) plus currency code. Mutable tables have `created_at`, `updated_at`, `version`.
7. **Idempotency**: Endpoints that create attendance, RSVP, location batches, payments accept an `Idempotency-Key` header; the same key with a different body returns 409.
8. **Cursor Pagination**: Default 20, maximum 100.
9. **Audit Log**: Append-only log for login failures, role changes, consent changes, applications decisions, exports, admin actions.
10. **Feature Flags**: All R2 (payments, bookings, marketplace, rentals, expenses, roadside) and R3 (AI, offline maps, premium) modules are stubbed and disabled; their endpoints return 404 while disabled.
11. **Privacy**: Never return exact rider coordinates from discovery; never log OTPs, tokens, phone numbers in full, or personal data.
12. **Secrets & Config**: Never commit secrets. Configuration comes from environment variables (`.env`, git-ignored; keep `.env.example` current).
13. **CI/CD**: The project follows a GitHub Actions pipeline (Task A2). Every task must keep CI green. Database migrations must be backward compatible. Never push straight to main once branch protection is on: use a branch and a pull request.

### Dev and Sharing
- `ENV=dev` enables:
  - A fixed OTP (`DEV_FIXED_OTP`) that works ONLY for phone numbers listed in `ALLOWED_TEST_PHONES` (comma separated).
  - All other numbers get a random OTP printed in server log.
  - In any `ENV` other than `dev`, the fixed OTP is impossible.
- CORS: allow all origins in dev (the Flutter app and partner will call through an ngrok URL). Configurable list otherwise.
- The partner reaches the API through an ngrok tunnel to port 8000. Middleware never fails because of the `ngrok-skip-browser-warning` header.
- Provide `scripts/seed_dev.py` that creates dev data (only when `ENV=dev`): cities, interests, 3 test riders, 1 club owner, 1 moderator, 1 captain, 1 platform admin, 1 sample club. Print the test phone numbers.

