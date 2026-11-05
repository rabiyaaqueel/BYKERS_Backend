# BYKERS Backend: CI/CD Pipeline Guide

This guide explains how automated testing, security scanning, container building, and deployment work in the BYKERS backend.

---

## 1. What is CI/CD? (In Simple English)

- **CI (Continuous Integration):** Every time you push code or open a Pull Request (PR), automated robots check your code. They test your code formatting (`ruff`), type safety (`mypy`), security vulnerabilities (`pip-audit`, `bandit`), reversible database migrations (`alembic`), and run all unit/integration tests with test coverage (`pytest`).
- **CD (Continuous Delivery & Deployment):** When tested code is merged into `main`, another robot packages your application into a Docker container image, stores it securely in GitHub Container Registry (GHCR), and safely rolls out the update to the cloud.

---

## 2. The Pipelines at a Glance

### `.github/workflows/ci.yml` (The Safety Inspector)
Triggered on **every pull request** and **every push to `main`**.
It runs 3 independent jobs:

1. **`test`**:
   - Starts a real PostgreSQL 16 + PostGIS service container.
   - Verifies formatting: `ruff format --check .`
   - Verifies code quality: `ruff check .`
   - Checks types: `mypy app`
   - Tests reversible database migrations: runs `alembic upgrade head`, then `alembic downgrade -1`, then `alembic upgrade head` again. This guarantees you never ship a migration that cannot be rolled back!
   - Runs unit tests and verifies code coverage (`fail-under = 60%`).
   - Exports the API specification (`docs/openapi.json`) and fails if you changed API routes without committing the updated schema file.
2. **`security`**:
   - Scans dependencies for known CVEs (`pip-audit`).
   - Scans code for common security bugs (`bandit`).
   - Scans git history for leaked API keys, tokens, or passwords (`gitleaks`).
3. **`docker`**:
   - Builds the production multi-stage Docker image.
   - Scans the container image for OS/library vulnerabilities using Trivy.

---

### `.github/workflows/cd.yml` (The Cloud Deployer)
Triggered on:
- **Push to `main`:** Builds and tags the Docker image (`ghcr.io/<owner>/bykers-backend:<sha>`), then conditionally deploys to **Staging** (if `DEPLOY_TARGET` is configured).
- **Git Release Tag (`v*.*.*`, e.g. `v0.1.0`):** Prompts for approval to deploy to **Production**, performs expand-first migrations, updates Azure Container Apps, runs live smoke tests, and automatically rolls back if health checks fail.

---

## 3. How to Inspect a Failed CI Run

If a red **X** appears on your GitHub Pull Request:
1. Open the Pull Request on GitHub.
2. Click on the red **Details** link next to the failed check.
3. Click on the failed step (e.g., `Run Pytest & Coverage` or `Check for OpenAPI drift`).
4. Read the error message in the logs:
   - **Ruff failed?** Run `.\.venv\Scripts\ruff format .` and `.\.venv\Scripts\ruff check --fix .` locally.
   - **Mypy failed?** Fix the type annotations highlighted in the logs.
   - **OpenAPI drift?** You added/modified an endpoint. Run `.\.venv\Scripts\python scripts/export_openapi.py` and commit `docs/openapi.json`.
   - **Tests failed?** Run `.\.venv\Scripts\pytest` locally to reproduce and fix.
5. Re-run local checks before pushing again:
   ```powershell
   .\scripts\check.ps1
   ```

---

## 4. Branch Protection Rules on `main`

To prevent accidental breakages, protect the `main` branch on GitHub:

1. Go to your GitHub repository -> **Settings** -> **Branches**.
2. Under "Branch protection rules", click **Add branch ruleset** or **Add rule**.
3. **Branch name pattern:** `main`.
4. Check the following settings:
   - [x] **Require a pull request before merging**
     - Require approvals: `1`
     - Dismiss stale pull request approvals when new commits are pushed: `Checked`
     - Require review from Code Owners: `Checked`
   - [x] **Require status checks to pass before merging**
     - Status checks required:
       - `test` (the CI test job)
       - `security` (the security scans)
       - `docker` (the container build check)
   - [x] **Do not allow bypassing the above settings**
   - [x] **Do not allow force pushes (`git push --force`)**
   - [x] **Do not allow deletions**
5. Click **Create** / **Save changes**.

---

## 5. Required Secrets and Variables

Configure these in GitHub repository under **Settings -> Secrets and variables -> Actions**:

### Repository Variables (Plain Text)
| Variable Name | Required For | Description | Example / Notes |
|---|---|---|---|
| `DEPLOY_TARGET` | Staging / Prod CD | Triggers CD deployment step | Set to `azure` when cloud infrastructure is created. Default is unset (skips deployment until ready). |
| `STAGING_CONTAINER_APP_NAME` | Staging CD | Azure Container App name | e.g. `bykers-api-staging` |
| `PROD_CONTAINER_APP_NAME` | Production CD | Azure Container App name | e.g. `bykers-api-prod` |
| `STAGING_API_URL` | Staging CD | URL for post-deploy smoke tests | e.g. `https://api-staging.bykers.app` |
| `PROD_API_URL` | Production CD | URL for post-deploy smoke tests | e.g. `https://api.bykers.app` |

### Repository Secrets (Encrypted)
| Secret Name | Required For | Description |
|---|---|---|
| `AZURE_CLIENT_ID` | Cloud Auth | Microsoft Entra App registration Client ID (OIDC) |
| `AZURE_TENANT_ID` | Cloud Auth | Azure Tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Cloud Auth | Azure Subscription ID |
| `AZURE_RESOURCE_GROUP` | Cloud Deployment | Azure Resource Group name |
| `STAGING_DATABASE_URL` | Staging Migration | Connection string for staging PostgreSQL |
| `PROD_DATABASE_URL` | Prod Migration | Connection string for production PostgreSQL |

> [!NOTE]
> GitHub provides `GITHUB_TOKEN` automatically for pulling and pushing images to GitHub Container Registry (`ghcr.io`). You do not need to configure Docker Hub credentials.

---

## 6. How to Deploy a Production Release

When you are ready to cut a new release:
1. Ensure all PRs are merged into `main` and all CI tests are green.
2. In PowerShell, pull latest `main`, tag it with a semantic version, and push the tag:
   ```powershell
   git checkout main
   git pull origin main
   git tag v0.1.0 -m "Release v0.1.0: Foundation and CI/CD"
   git push origin v0.1.0
   ```
3. GitHub Actions triggers the `deploy-production` job in `.github/workflows/cd.yml`.
4. If an Environment Protection Rule is set for `production`, authorized reviewers receive an approval prompt in GitHub before live deployment proceeds.
5. Once approved:
   - Expand-first database migrations run.
   - The container app is updated to image tag `v0.1.0`.
   - Automated smoke tests probe `PROD_API_URL/api/v1/health`.
   - If smoke tests fail, the workflow immediately triggers an automated rollback to the previous container revision and reports the incident.
