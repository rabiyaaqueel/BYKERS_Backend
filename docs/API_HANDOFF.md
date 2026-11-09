# BYKERS Backend - Frontend Integration & API Handoff

This document provides complete API reference contracts for frontend engineers (Flutter / Mobile).

---

## 1. Authentication & Onboarding Flow

### Screen Flow:
1. **Welcome Screen**: Select language (`en`, `te`, `hi`).
2. **Phone Number**: User enters phone number.
   - `POST /api/v1/auth/otp/request`
     - Body: `{"phone": "+919848012345", "channel": "sms"}`
     - Response: `{"message": "OTP sent successfully", "retry_after": 60, "expires_in": 300}`
3. **Verify OTP**: User enters 6-digit OTP.
   - `POST /api/v1/auth/otp/verify`
     - Body: `{"phone": "+919848012345", "otp": "123456", "device_id": "uuid-or-unique-string", "platform": "android"}`
     - Response:
       ```json
       {
         "access_token": "eyJhbGciOi...",
         "token_type": "bearer",
         "session_id": "...",
         "user_id": "...",
         "status": "pending_profile" // or "active" if returning user
       }
       ```
4. **Lookup Reference Data (Dropdowns & Catalogs)**:
   - `GET /api/v1/cities`: List of cities (returns `[{"id": "...", "name": "Hyderabad", "state": "Telangana"}]`).
   - `GET /api/v1/interests`: List of riding interests (`[{"code": "touring", "name_en": "Touring"}, ...]`).
   - `GET /api/v1/notices/current`: Current active legal versions (`terms.version = "v1.0"`, `privacy.version = "v1.0"`).
5. **Create Account (Screen 4)**:
   - `POST /api/v1/me/account-setup`
     - Headers: `Authorization: Bearer <access_token>`
     - Body:
       ```json
       {
         "display_name": "John Doe",
         "city_id": "c1f76d49-43c2-49cf-8ae4-0b6ec8cce0aa",
         "locale": "en",
         "adult_declaration": true,
         "accepted_terms_version": "v1.0",
         "accepted_privacy_version": "v1.0",
         "marketing_consent": false,
         "interests": ["touring", "adventure"]
       }
       ```
6. **Riding Profile Details (Screen 5 - Optional or Subsequent)**:
   - `PATCH /api/v1/me/profile`
     - Body:
       ```json
       {
         "languages": ["en", "te"],
         "interests": ["touring", "adventure", "beginners"],
         "bio": "Weekend highway cruiser"
       }
       ```

---

## 2. Task E: Motorcycle Garage (Modules M03 & M21)

All endpoints require:
- Header: `Authorization: Bearer <access_token>`
- Interface: `rider_app` (automatically set for rider sessions; organizer/staff tokens receive `403 FORBIDDEN_INTERFACE`).
- Guest tokens are not permitted (`401 UNAUTHORIZED`).

### 2.1 Screen: "Add a Motorcycle" (Right After Onboarding)
- **Skip Button**: Skips motorcycle creation. No API call needed. Onboarding is already complete.
- **Save Motorcycle Button**: Calls `POST /api/v1/me/bikes` with an `Idempotency-Key` header.

#### `POST /api/v1/me/bikes`
Creates a new motorcycle in rider's garage.
- **Headers**:
  - `Authorization: Bearer <access_token>`
  - `Idempotency-Key: <unique-uuid>` (prevents duplicate bike creation on double tap)
- **Request Body**:
  ```json
  {
    "make": "Royal Enfield",
    "model": "Himalayan 450",
    "year": 2024,
    "powertrain": "petrol",
    "nickname": "Sherpa",
    "odometer_km": 1500,
    "registration": "TS09AB1234"
  }
  ```
  - `make`: string, required (trimmed)
  - `model`: string, required (trimmed)
  - `year`: int, required (1950 to next year)
  - `powertrain`: string (`petrol`, `electric`, `hybrid`), default `"petrol"`
  - `nickname`: string, optional
  - `odometer_km`: int, optional (0 to 999999)
  - `registration`: string, optional (alphanumeric, 6-12 chars). Will be encrypted at rest.
- **Response (`201 Created`)**:
  ```json
  {
    "id": "7b587a32-9b2d-425f-bcad-62bcfbe282ef",
    "make": "Royal Enfield",
    "model": "Himalayan 450",
    "year": 2024,
    "powertrain": "petrol",
    "nickname": "Sherpa",
    "odometer_km": 1500,
    "registration_masked": "******1234",
    "is_preferred": true,
    "photos": [],
    "created_at": "2026-11-06T14:30:00Z",
    "version": 1
  }
  ```
  *(Note: The first active bike added by a rider automatically becomes `is_preferred: true`)*

---

### 2.2 Garage Management Endpoints

#### `GET /api/v1/me/bikes`
Lists user's bikes. Active bikes listed first (preferred bike first), then archived bikes if `include_archived=true`.
- **Query Params**: `include_archived` (boolean, default `false`)
- **Response (`200 OK`)**: List of `BikeOut` objects.

#### `GET /api/v1/me/bikes/{id}`
Returns details of a specific bike.
- Returns `404 NOT_FOUND` if bike belongs to another user.

#### `PATCH /api/v1/me/bikes/{id}`
Updates motorcycle details with optimistic locking concurrency.
- **Request Body**:
  ```json
  {
    "version": 1,
    "nickname": "Thunderbolt",
    "odometer_km": 2200,
    "registration": "TS09CD5678"
  }
  ```
  - `version`: int, **required**. Returns `409 CONFLICT` if version does not match database version.
  - `registration`: pass `""` or `null` to clear registration, or provide new registration string.

#### `DELETE /api/v1/me/bikes/{id}`
Archives motorcycle (soft delete, retains ride history).
- If the archived bike was `is_preferred: true`, the system automatically promotes the rider's most recently added active bike to preferred.
- **Response (`200 OK`)**: `{"message": "Motorcycle archived successfully"}`.

#### `POST /api/v1/me/bikes/{id}/preferred`
Atomically switches preferred bike to the specified bike ID.
- **Response (`200 OK`)**: Updated `BikeOut` with `is_preferred: true`.

---

### 2.3 Photos (Storage & Security)

#### `POST /api/v1/me/bikes/{id}/photos/upload-intent`
Requests a short-lived presigned upload URL for a bike photo.
- **Validation**: JPEG, PNG, or WebP; maximum 5 MB; maximum 5 photos per bike.
- **Request Body**:
  ```json
  {
    "mime_type": "image/jpeg",
    "byte_size": 2048576,
    "display_order": 0
  }
  ```
- **Response (`200 OK`)**:
  ```json
  {
    "media_id": "...",
    "upload_url": "http://...",
    "object_key": "...",
    "expires_in_seconds": 900
  }
  ```

#### `POST /api/v1/me/bikes/{id}/photos/complete`
Notifies backend upload is finished. Photo is linked to bike once scan state is clean.
- **Request Body**: `{"media_id": "..."}`
- **Response (`200 OK`)**: Updated `BikeOut` including photos list.

---

### 2.4 M21: Maintenance Records & Documents

#### `GET /api/v1/me/bikes/{id}/maintenance`
Lists maintenance history.

#### `POST /api/v1/me/bikes/{id}/maintenance`
Logs maintenance service. Automatically updates bike odometer if the service reading is higher.
- **Request Body**:
  ```json
  {
    "service_date": "2026-11-01T10:00:00Z",
    "odometer_km": 1500,
    "category": "oil_change",
    "notes": "Engine oil & oil filter replacement",
    "invoice_media_id": null,
    "next_due_date": "2027-05-01T10:00:00Z",
    "next_due_km": 6500
  }
  ```

#### `GET /api/v1/me/bikes/{id}/documents`
Lists documents with private signed download URLs.

#### `POST /api/v1/me/bikes/{id}/documents`
Attaches insurance, registration, pollution, or licence document.
- **Request Body**:
  ```json
  {
    "type": "insurance",
    "expires_on": "2027-11-01T00:00:00Z",
    "private_media_id": "...",
    "sharing_policy": "private"
  }
  ```

---

### 2.5 Profile Completeness on `GET /api/v1/me`
`GET /api/v1/me` includes:
```json
{
  "profile_completeness": {
    "has_bike": true,
    "active_bikes_count": 1,
    "profile_percent": 100
  }
}
```
If rider skips adding a bike, `has_bike` is `false` and `active_bikes_count` is `0`, but rider can still access all features not requiring a bike.

---

### 2.6 Standard Error Envelope
All error responses strictly adhere to the standard envelope:
```json
{
  "code": "VALIDATION_ERROR",
  "message": "Field validation failed",
  "details": {
    "registration": "Registration must be 6 to 12 alphanumeric characters."
  },
  "request_id": "req_12345"
}
```
Use the `details` map in Flutter to display errors directly under the corresponding input widget.
