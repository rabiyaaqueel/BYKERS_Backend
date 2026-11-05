<#
.SYNOPSIS
    Runs local quality, linting, type-checking, test, and OpenAPI checks matching CI.
.DESCRIPTION
    Execute this script before pushing any commit or opening a pull request:
    .\scripts\check.ps1
#>

$ErrorActionPreference = "Stop"

# Determine project root directory
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "       BYKERS Backend - Pre-push CI Check         " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Root: $ProjectRoot`n" -ForegroundColor Gray

# Locate virtual environment binaries
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$VenvRuff   = Join-Path $ProjectRoot ".venv\Scripts\ruff.exe"
$VenvMypy   = Join-Path $ProjectRoot ".venv\Scripts\mypy.exe"
$VenvPytest = Join-Path $ProjectRoot ".venv\Scripts\pytest.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "[ERROR] Virtual environment not found at .venv\Scripts\python.exe." -ForegroundColor Red
    Write-Host "Please create it and install requirements first: python -m venv .venv; pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

function Run-Step {
    param (
        [string]$Title,
        [scriptblock]$Command
    )
    Write-Host "`n>>> [STEP] $Title..." -ForegroundColor Yellow
    try {
        & $Command
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[FAIL] $Title failed with exit code $LASTEXITCODE." -ForegroundColor Red
            exit $LASTEXITCODE
        }
        Write-Host "[PASS] $Title succeeded." -ForegroundColor Green
    }
    catch {
        Write-Host "[FAIL] $Title threw an exception: $_" -ForegroundColor Red
        exit 1
    }
}

# 1. Ruff Format Check
Run-Step "1/6 Ruff Format Check" {
    & $VenvRuff format --check .
}

# 2. Ruff Linter Check
Run-Step "2/6 Ruff Lint Check" {
    & $VenvRuff check .
}

# 3. Mypy Type Check
Run-Step "3/6 Mypy Static Type Analysis" {
    & $VenvMypy app
}

# 4. Pytest with Coverage
Run-Step "4/6 Pytest & Coverage Threshold" {
    & $VenvPytest --cov=app --cov-report=term-missing
}

# 5. OpenAPI Schema Generation
Run-Step "5/6 Export OpenAPI Schema" {
    & $VenvPython scripts/export_openapi.py
}

# 6. OpenAPI Drift Detection (git diff check)
Run-Step "6/6 OpenAPI Spec Drift Check" {
    git diff --exit-code docs/openapi.json
}

Write-Host "`n==================================================" -ForegroundColor Green
Write-Host " [SUCCESS] All checks passed cleanly! Safe to push. " -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
