"""Object storage for uploaded files.

`ObjectStorage` has a local-disk and an S3-compatible implementation. `EncryptedStorage`
wraps either one and AES-256-GCM encrypts every object before it leaves the process, so
files are encrypted at rest regardless of what the storage provider offers. The object
key is bound into the ciphertext (AAD): a blob copied to another key will not decrypt.
"""

import asyncio
import base64
import os
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


class StorageError(RuntimeError):
    """The storage backend failed (unreachable, permission denied, ...)."""


class ObjectNotFoundError(StorageError):
    pass


class ObjectStorage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...  # idempotent
    async def check(self) -> bool: ...


def _safe_key(key: str) -> str:
    if key.startswith("/") or ".." in key.split("/") or "\\" in key:
        raise ValueError("Invalid object key")
    return key


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / _safe_key(key)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)  # atomic: readers never see a half-written file

        try:
            await asyncio.to_thread(write)
        except OSError as exc:
            raise StorageError(f"local write failed: {type(exc).__name__}") from exc

    async def get(self, key: str) -> bytes:
        try:
            return await asyncio.to_thread(self._path(key).read_bytes)
        except FileNotFoundError as exc:
            raise ObjectNotFoundError(key) from exc
        except OSError as exc:
            raise StorageError(f"local read failed: {type(exc).__name__}") from exc

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._path(key).unlink, True)
        except OSError as exc:
            raise StorageError(f"local delete failed: {type(exc).__name__}") from exc

    async def check(self) -> bool:
        def probe() -> bool:
            self.root.mkdir(parents=True, exist_ok=True)
            return os.access(self.root, os.W_OK)

        try:
            return await asyncio.to_thread(probe)
        except OSError:
            return False


class S3Storage:
    def __init__(self, *, endpoint: str, region: str, access_key: str, secret_key: str,
                 bucket: str):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint or None,
            region_name=region,
            aws_access_key_id=access_key or None,
            aws_secret_access_key=secret_key or None,
            config=Config(retries={"max_attempts": 3, "mode": "standard"},
                          connect_timeout=5, read_timeout=30),
        )

    async def _call(self, method: str, **kwargs):
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return await asyncio.to_thread(getattr(self.client, method), **kwargs)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404", "NotFound"):
                raise ObjectNotFoundError(kwargs.get("Key", "")) from exc
            raise StorageError(f"s3 {method} failed: {code}") from exc
        except BotoCoreError as exc:
            raise StorageError(f"s3 {method} failed: {type(exc).__name__}") from exc

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await self._call("put_object", Bucket=self.bucket, Key=_safe_key(key), Body=data,
                         ContentType="application/octet-stream")

    async def get(self, key: str) -> bytes:
        response = await self._call("get_object", Bucket=self.bucket, Key=_safe_key(key))
        return await asyncio.to_thread(response["Body"].read)

    async def delete(self, key: str) -> None:
        await self._call("delete_object", Bucket=self.bucket, Key=_safe_key(key))

    async def check(self) -> bool:
        try:
            await self._call("head_bucket", Bucket=self.bucket)
            return True
        except StorageError:
            return False


_MAGIC = b"TAE1"  # format marker for encrypted objects


class EncryptedStorage:
    def __init__(self, inner: ObjectStorage, key: bytes):
        if len(key) != 32:
            raise ValueError("STORAGE_ENCRYPTION_KEY must decode to 32 bytes")
        self.inner = inner
        self.aead = AESGCM(key)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        nonce = os.urandom(12)
        blob = _MAGIC + nonce + self.aead.encrypt(nonce, data, key.encode())
        await self.inner.put(key, blob, content_type)

    async def get(self, key: str) -> bytes:
        blob = await self.inner.get(key)
        if not blob.startswith(_MAGIC):
            raise StorageError("object is not encrypted with this key format")
        nonce, ciphertext = blob[4:16], blob[16:]
        return self.aead.decrypt(nonce, ciphertext, key.encode())

    async def delete(self, key: str) -> None:
        await self.inner.delete(key)

    async def check(self) -> bool:
        return await self.inner.check()


@lru_cache
def get_storage() -> ObjectStorage:
    settings = get_settings()
    inner: ObjectStorage
    if settings.STORAGE_BACKEND == "s3":
        inner = S3Storage(
            endpoint=settings.OBJECT_STORAGE_ENDPOINT,
            region=settings.OBJECT_STORAGE_REGION,
            access_key=settings.OBJECT_STORAGE_ACCESS_KEY,
            secret_key=settings.OBJECT_STORAGE_SECRET_KEY,
            bucket=settings.OBJECT_STORAGE_BUCKET,
        )
    else:
        inner = LocalStorage(Path(settings.STORAGE_LOCAL_PATH))
    if settings.STORAGE_ENCRYPTION_KEY:
        return EncryptedStorage(inner, base64.b64decode(settings.STORAGE_ENCRYPTION_KEY))
    return inner
