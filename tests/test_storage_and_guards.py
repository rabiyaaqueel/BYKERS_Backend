"""Tests for Storage Provider and Environment Safety Guards."""

import pytest

from app.core.config import Settings
from app.core.storage import LocalStorageProvider, get_storage_provider


@pytest.mark.asyncio
async def test_local_storage_provider_lifecycle(tmp_path):
    """Local storage provider properly handles file upload, URL generation, check and deletion."""
    provider = LocalStorageProvider(base_dir=str(tmp_path))

    key = "test_dir/sample_file.txt"
    content = b"Bykers storage verification content"

    # Upload
    uploaded_key = await provider.upload(key=key, data=content, content_type="text/plain")
    assert uploaded_key == key
    assert await provider.exists(key) is True

    # Download URL
    url = await provider.get_download_url(key)
    assert url == f"/api/v1/storage/{key}"

    # Delete
    deleted = await provider.delete(key)
    assert deleted is True
    assert await provider.exists(key) is False

    # Second delete returns False
    assert await provider.delete(key) is False


def test_get_storage_provider():
    """get_storage_provider returns instance of LocalStorageProvider in dev/test."""
    provider = get_storage_provider()
    assert isinstance(provider, LocalStorageProvider)


def test_startup_refusal_when_dev_fixed_otp_set_in_non_dev():
    """Application Settings must refuse startup if DEV_FIXED_OTP is set outside ENV=dev."""
    with pytest.raises(ValueError) as exc:
        Settings(ENV="prod", DEV_FIXED_OTP="123456", STORAGE_PROVIDER="azure")
    assert "DEV_FIXED_OTP must not be configured" in str(exc.value)

    with pytest.raises(ValueError) as exc_staging:
        Settings(ENV="staging", DEV_FIXED_OTP="123456", STORAGE_PROVIDER="azure")
    assert "DEV_FIXED_OTP must not be configured" in str(exc_staging.value)


def test_startup_refusal_when_local_storage_in_staging_or_prod():
    """Application Settings must refuse startup if STORAGE_PROVIDER is local in staging/prod."""
    with pytest.raises(ValueError) as exc_prod:
        Settings(ENV="prod", DEV_FIXED_OTP=None, STORAGE_PROVIDER="local")
    assert "STORAGE_PROVIDER cannot be 'local'" in str(exc_prod.value)

    with pytest.raises(ValueError) as exc_staging:
        Settings(ENV="staging", DEV_FIXED_OTP=None, STORAGE_PROVIDER="local")
    assert "STORAGE_PROVIDER cannot be 'local'" in str(exc_staging.value)
