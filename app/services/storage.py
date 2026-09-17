import mimetypes
import uuid

import boto3
from botocore.client import Config as BotoConfig
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from app.config import settings

ALLOWED_AUDIO_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/x-m4a",
    "audio/ogg",
    "audio/flac",
}
MAX_UPLOAD_BYTES = 60 * 1024 * 1024  # 60 MB — adjust if you need longer tracks/stems


def _client():
    if not settings.STORAGE_BUCKET_NAME:
        raise HTTPException(
            status_code=503,
            detail="Audio storage is not configured (missing STORAGE_BUCKET_NAME).",
        )
    return boto3.client(
        "s3",
        endpoint_url=settings.STORAGE_ENDPOINT_URL or None,
        aws_access_key_id=settings.STORAGE_ACCESS_KEY_ID or None,
        aws_secret_access_key=settings.STORAGE_SECRET_ACCESS_KEY or None,
        region_name=settings.STORAGE_REGION or None,
        config=BotoConfig(signature_version="s3v4"),
    )


def _validate(filename: str, content_type: str | None, size: int):
    if size == 0:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")
    if size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (60MB limit).")
    guessed = content_type or mimetypes.guess_type(filename)[0]
    if guessed not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported audio type: {guessed}")


async def upload_audio_file(
    owner_id: str, filename: str, content_type: str | None, data: bytes
) -> tuple[str, str]:
    """
    Uploads raw audio bytes to object storage.
    Returns (storage_key, public_url) — both are persisted on the Upload row:
    storage_key is used internally for deletion, storage_url is what the client plays.
    """
    _validate(filename, content_type, len(data))
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    key = f"uploads/{owner_id}/{uuid.uuid4()}.{ext}"

    def _put():
        client = _client()
        client.put_object(
            Bucket=settings.STORAGE_BUCKET_NAME,
            Key=key,
            Body=data,
            ContentType=content_type or "application/octet-stream",
        )

    try:
        await run_in_threadpool(_put)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"Could not upload to storage: {type(e).__name__}: {e}"
        )

    if settings.STORAGE_PUBLIC_BASE_URL:
        public_url = f"{settings.STORAGE_PUBLIC_BASE_URL.rstrip('/')}/{key}"
    else:
        # No public base URL configured — bucket is presumably private.
        # Caller/frontend will need presigned URLs added later to play these back.
        public_url = key

    return key, public_url


async def delete_audio_file(key: str) -> None:
    def _delete():
        client = _client()
        client.delete_object(Bucket=settings.STORAGE_BUCKET_NAME, Key=key)

    try:
        await run_in_threadpool(_delete)
    except Exception:
        # Best-effort: don't let a storage hiccup block deleting the DB row.
        pass


def generate_presigned_url(key: str, expires_in: int = 3600) -> str:
    """
    Generate a temporary signed GET URL for a private object.
    This is local cryptographic signing, not a network call, so no threadpool needed.
    Default expiry is 1 hour — bump expires_in (seconds) if the frontend needs longer-lived links.
    """
    client = _client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.STORAGE_BUCKET_NAME, "Key": key},
        ExpiresIn=expires_in,
    )
