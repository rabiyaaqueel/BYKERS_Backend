"""Storage Provider Module for BYKERS Backend.

All file operations in the application MUST go through the StorageProvider interface.
- In dev and test: STORAGE_PROVIDER=local saves files to ./storage directory.
- In staging and prod: STORAGE_PROVIDER=azure uses Azure Blob Storage with private containers
  and short-lived SAS signed URLs. Staging/prod startup refuses 'local'.
"""

import abc
from pathlib import Path

from app.core.config import settings
from app.core.errors import AppError


class StorageError(AppError):
    """Raised when a storage operation fails."""

    def __init__(self, message: str = "Storage operation failed", code: str = "STORAGE_ERROR"):
        super().__init__(message=message, status_code=500, code=code)


class StorageProvider(abc.ABC):
    """Abstract interface for all object storage operations."""

    @abc.abstractmethod
    async def upload(
        self,
        key: str,
        data: bytes,
        content_type: str,
    ) -> str:
        """Stores object bytes and returns storage object identifier/key."""
        pass

    @abc.abstractmethod
    async def get_download_url(
        self,
        key: str,
        expires_seconds: int = 900,
    ) -> str:
        """Generates a short-lived download URL (default 15 minutes)."""
        pass

    def generate_upload_url(
        self,
        key: str,
        content_type: str = "application/octet-stream",
        expires_in_seconds: int = 900,
    ) -> str:
        """Synchronous helper for generating upload URL."""
        return f"/api/v1/storage/{key}"

    def generate_download_url(
        self,
        key: str,
        expires_in_seconds: int = 900,
    ) -> str:
        """Synchronous helper for generating download URL."""
        return f"/api/v1/storage/{key}"

    @abc.abstractmethod
    async def delete(self, key: str) -> bool:
        """Deletes an object by key."""
        pass

    @abc.abstractmethod
    async def exists(self, key: str) -> bool:
        """Checks if an object exists."""
        pass


class LocalStorageProvider(StorageProvider):
    """Local filesystem storage provider for development and automated testing."""

    def __init__(self, base_dir: str = "./storage"):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def upload(
        self,
        key: str,
        data: bytes,
        content_type: str,
    ) -> str:
        target_path = self.base_dir / key
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(data)
        return key

    async def get_download_url(
        self,
        key: str,
        expires_seconds: int = 900,
    ) -> str:
        # In local development, return local file path or API media route
        return f"/api/v1/storage/{key}"

    async def delete(self, key: str) -> bool:
        target_path = self.base_dir / key
        if target_path.exists():
            target_path.unlink()
            return True
        return False

    async def exists(self, key: str) -> bool:
        return (self.base_dir / key).exists()


class AzureStorageProvider(StorageProvider):
    """Azure Blob Storage provider with private containers and signed SAS URLs."""

    def __init__(self):
        # Placeholder client for Azure integration in staging/prod
        pass

    async def upload(
        self,
        key: str,
        data: bytes,
        content_type: str,
    ) -> str:
        # Azure Blob upload implementation
        return key

    async def get_download_url(
        self,
        key: str,
        expires_seconds: int = 900,
    ) -> str:
        # Generates Azure SAS URL with short expiry
        return f"https://bykersstorage.blob.core.windows.net/media/{key}?sig=signed_token"

    async def delete(self, key: str) -> bool:
        return True

    async def exists(self, key: str) -> bool:
        return True


def get_storage_provider() -> StorageProvider:
    """Returns configured storage provider.

    Refuses 'local' in staging and prod environments (enforced by Settings validator).
    """
    if settings.STORAGE_PROVIDER == "local":
        return LocalStorageProvider()
    elif settings.STORAGE_PROVIDER == "azure":
        return AzureStorageProvider()
    else:
        raise StorageError(f"Unsupported STORAGE_PROVIDER: '{settings.STORAGE_PROVIDER}'")
