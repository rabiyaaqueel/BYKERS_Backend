# Motorcycle Garage (Task E / Modules M03 & M21) - PowerShell Demo Guide

Follow these PowerShell steps to test and verify all garage features against a running local backend server.

---

## 0. Prerequisite: Start the Server

Ensure PostgreSQL is running and start the backend:
```powershell
# In PowerShell:
cd C:\Users\USER\Desktop\BYKERS_Backend
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

---

## 1. Authenticate Rider & Obtain Access Token

```powershell
$BaseUrl = "http://127.0.0.1:8000/api/v1"

# Request OTP
$otpReq = Invoke-RestMethod -Method Post -Uri "$BaseUrl/auth/otp/request" `
    -ContentType "application/json" `
    -Body '{"phone": "+919848011223", "channel": "sms"}'
Write-Host "OTP Request response: $($otpReq | ConvertTo-Json -Compress)"

# Verify OTP (Dev OTP is 123456)
$verifyRes = Invoke-RestMethod -Method Post -Uri "$BaseUrl/auth/otp/verify" `
    -ContentType "application/json" `
    -Body '{"phone": "+919848011223", "otp": "123456", "device_id": "demo-device-01", "platform": "android"}'

$Token = $verifyRes.access_token
$Headers = @{
    "Authorization" = "Bearer $Token"
    "Content-Type"  = "application/json"
}
Write-Host "Authenticated as user $($verifyRes.user_id)"

# Complete Account Setup if new user
if ($verifyRes.status -eq "pending_profile") {
    $setupPayload = @{
        display_name = "Rider Demo"
        locale = "en"
        adult_declaration = $true
        accepted_terms_version = "v1.0"
        accepted_privacy_version = "v1.0"
        marketing_consent = $false
        interests = @("touring")
    } | ConvertTo-Json
    Invoke-RestMethod -Method Post -Uri "$BaseUrl/me/account-setup" -Headers $Headers -Body $setupPayload | Out-Null
    Write-Host "Profile setup complete."
}
```

---

## 2. Step 1: Add First Motorcycle (Minimal / Standard Fields)

The first motorcycle added automatically becomes `is_preferred = true`.

```powershell
$Bike1Payload = @{
    make = "Royal Enfield"
    model = "Himalayan 450"
    year = 2024
    powertrain = "petrol"
    nickname = "Sherpa"
    odometer_km = 1200
    registration = "TS09EA1234"
} | ConvertTo-Json

# Using Idempotency-Key header to prevent duplicate creations
$Bike1Headers = $Headers.Clone()
$Bike1Headers["Idempotency-Key"] = [System.Guid]::NewGuid().ToString()

$Bike1 = Invoke-RestMethod -Method Post -Uri "$BaseUrl/me/bikes" -Headers $Bike1Headers -Body $Bike1Payload
Write-Host "`n=== Added Bike 1 (Auto Preferred) ===" -ForegroundColor Green
$Bike1 | ConvertTo-Json
```

Expected output:
- `is_preferred`: `true`
- `registration_masked`: `"******1234"`

---

## 3. Step 2: Add Second Motorcycle

The second active bike will have `is_preferred = false`.

```powershell
$Bike2Payload = @{
    make = "KTM"
    model = "390 Adventure"
    year = 2023
    powertrain = "petrol"
    nickname = "Orange Beast"
    odometer_km = 4500
    registration = "AP28AB5678"
} | ConvertTo-Json

$Bike2Headers = $Headers.Clone()
$Bike2Headers["Idempotency-Key"] = [System.Guid]::NewGuid().ToString()

$Bike2 = Invoke-RestMethod -Method Post -Uri "$BaseUrl/me/bikes" -Headers $Bike2Headers -Body $Bike2Payload
Write-Host "`n=== Added Bike 2 ===" -ForegroundColor Green
$Bike2 | ConvertTo-Json
```

Expected output:
- `is_preferred`: `false`
- `registration_masked`: `"******5678"`

---

## 4. Step 3: Switch Preferred Motorcycle

Atomically switch the preferred bike to the second bike (KTM).

```powershell
$PreferredRes = Invoke-RestMethod -Method Post -Uri "$BaseUrl/me/bikes/$($Bike2.id)/preferred" -Headers $Headers
Write-Host "`n=== Switched Preferred Bike to Bike 2 ===" -ForegroundColor Green
$PreferredRes | ConvertTo-Json

# Verify with GET /me/bikes that Bike 2 is now first and preferred
$AllBikes = Invoke-RestMethod -Method Get -Uri "$BaseUrl/me/bikes" -Headers $Headers
Write-Host "`n=== All Active Bikes (Preferred First) ===" -ForegroundColor Cyan
$AllBikes | Select-Object id, make, model, is_preferred | Format-Table
```

---

## 5. Step 4: Archive Motorcycle & Observe Promotion

Archive the currently preferred bike (`Bike 2`). The backend will automatically promote `Bike 1` to preferred.

```powershell
# Archive Bike 2
$ArchiveRes = Invoke-RestMethod -Method Delete -Uri "$BaseUrl/me/bikes/$($Bike2.id)" -Headers $Headers
Write-Host "`n=== Archived Bike 2 ===" -ForegroundColor Green
$ArchiveRes | ConvertTo-Json

# Verify Bike 1 is now automatically promoted back to preferred
$ActiveBikesAfterArchive = Invoke-RestMethod -Method Get -Uri "$BaseUrl/me/bikes" -Headers $Headers
Write-Host "`n=== Active Bikes After Archive (Bike 1 Auto-Promoted) ===" -ForegroundColor Cyan
$ActiveBikesAfterArchive | Select-Object id, make, model, is_preferred | Format-Table
```

---

## 6. Step 5: Check `profile_completeness` on `GET /me`

```powershell
$Me = Invoke-RestMethod -Method Get -Uri "$BaseUrl/me" -Headers $Headers
Write-Host "`n=== Profile Completeness on GET /me ===" -ForegroundColor Yellow
$Me.profile_completeness | ConvertTo-Json
```
