# BYKERS Backend

BYKERS is an integrated motorcycle community backend platform designed for riders in India (pilot city: Hyderabad, adults 18+).

This service is built with **FastAPI**, **SQLAlchemy 2.0 (async)**, **PostgreSQL 16 + PostGIS**, and **Pydantic v2**.

---

## 1. Prerequisites

- **Python 3.12** installed on Windows.
- **PostgreSQL 16** with **PostGIS** extension installed (local database: `gis_database`).
- **PowerShell** (Windows default terminal).
- **ngrok** installed at `C:\ngrok\ngrok.exe` (or in your system PATH).

---

## 2. Virtual Environment Setup

Open PowerShell and navigate to the project directory:

```powershell
cd C:\Users\USER\Desktop\BYKERS_Backend
```

Create and activate the Python virtual environment:

```powershell
# 1. Create a virtual environment named .venv
python -m venv .venv

# 2. Activate the virtual environment in PowerShell
.\.venv\Scripts\Activate.ps1

# (If PowerShell blocks script execution, run: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass)
```

Install the dependencies:

```powershell
pip install -r requirements.txt
```

---

## 3. Environment Configuration (`.env`)

Copy the example file to `.env`:

```powershell
Copy-Item .env.example .env
```

Open `.env` in your editor (e.g. VS Code, Notepad) and replace `YOUR_POSTGRES_PASSWORD` with your real PostgreSQL password:

```ini
DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD_HERE@127.0.0.1:5432/gis_database
```

> **Security Rule**: The `.env` file contains your private local database credentials and is automatically ignored by Git. Never commit or paste your `.env` or database password into chat.

---

## 4. Database Setup & PostGIS Extensions

Ensure PostgreSQL is running and you have a database called `gis_database`.

If you haven't created it yet, open `psql` or run in PowerShell:

```powershell
# Create gis_database if it doesn't exist yet
psql -U postgres -c "CREATE DATABASE gis_database;"
```

### Run Migrations with Alembic

Run the initial migration to enable the `postgis` and `pgcrypto` extensions and create the `system_settings` table:

```powershell
.\.venv\Scripts\alembic upgrade head
```

> **Note on PostGIS**: If Alembic reports that PostGIS is missing, install the **Spatial Extensions (PostGIS)** for your PostgreSQL version using PostgreSQL's **Application Stack Builder** (included with standard PostgreSQL Windows installer), then re-run `alembic upgrade head`.

---

## 5. Run the Application

Start the FastAPI development server with uvicorn:

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The application will be live at:
- **Root Health Check**: http://127.0.0.1:8000/health
- **API v1 Health Check**: http://127.0.0.1:8000/api/v1/health
- **Interactive Swagger Docs**: http://127.0.0.1:8000/docs
- **ReDoc Documentation**: http://127.0.0.1:8000/redoc

A healthy check will return:
```json
{
  "status": "ok",
  "env": "dev",
  "database": "up",
  "postgis": "3.4.0 USE_GEOS=1 USE_PROJ=1 USE_STATS=1"
}
```

---

## 6. Run Tests & Linter

Run the automated test suite using `pytest`:

```powershell
.\.venv\Scripts\pytest -v
```

Check code style and formatting using `ruff`:

```powershell
.\.venv\Scripts\ruff check .
```

---

## 7. Share with ngrok

To share your local backend with your partner or test with mobile apps via your assigned ngrok dev domain:

1. Keep the backend running on port 8000 in your first PowerShell window:
   ```powershell
   .\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

2. Open a **second** PowerShell window and run:
   ```powershell
   C:\ngrok\ngrok.exe http --url=mountable-bubbling-enjoyably.ngrok-free.dev 8000
   ```

3. Tell the partner or mobile app to send the header:
   ```http
   ngrok-skip-browser-warning: true
   ```

The partner can now access the live API at:
- `https://mountable-bubbling-enjoyably.ngrok-free.dev/api/v1/health`
- `https://mountable-bubbling-enjoyably.ngrok-free.dev/docs`

---

## 8. Project Structure Explained (for Beginners)

```
BYKERS_Backend/
│
├── app/                        # Application source code
│   ├── main.py                 # FastAPI app factory, CORS, Request-ID, error handlers
│   ├── core/                   # Shared infrastructure and cross-cutting concerns
│   │   ├── config.py           # Settings loaded from .env via Pydantic
│   │   ├── db.py               # Async SQLAlchemy engine, session maker, health probe
│   │   ├── errors.py           # Standard error responses (Rule 4: code, message, details, request_id)
│   │   ├── logging.py          # Structured logging with automatic secret/PII redaction
│   │   ├── security.py         # Token hashing (SHA-256) and security helpers
│   │   ├── permissions.py      # The 14 system roles and authorization baseline
│   │   ├── audit.py            # Append-only audit logger
│   │   └── idempotency.py      # Idempotency store helpers
│   └── modules/                # Feature modules
│       └── health/             # Health check module
│           ├── router.py       # GET /health and GET /api/v1/health
│           └── schemas.py      # Pydantic schema for health response
│
├── migrations/                 # Alembic database migrations
│   ├── env.py                  # Async Alembic migration runner
│   ├── script.py.mako          # Template for new migrations
│   └── versions/               # Individual migration versions
│       └── 0001_initial_extensions_and_system.py # Enables postgis, pgcrypto, system_settings
│
├── tests/                      # Automated test suite
│   ├── conftest.py             # Async client test fixture
│   ├── test_health.py          # Health check endpoint tests
│   └── test_errors.py          # Request-ID, 404 format, and ngrok header tests
│
├── scripts/                    # Utility and development scripts
│   └── seed_dev.py             # Dev data seeding placeholder
│
├── docs/                       # Project documentation
│   └── CONTEXT.md              # Complete architectural baseline & requirements (Prompt 0)
│
├── .env.example                # Safe template for environment variables
├── .gitignore                  # Git ignore rules (.env, .venv, etc.)
├── alembic.ini                 # Alembic migration configuration
├── pyproject.toml              # Ruff and Pytest settings
├── requirements.txt            # Python package dependencies
└── README.md                   # Setup guide and instructions
```

