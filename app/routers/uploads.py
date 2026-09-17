from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Upload, User
from app.schemas import UploadRead
from app.auth import get_current_user
from app.services.storage import delete_audio_file, generate_presigned_url, upload_audio_file

router = APIRouter(prefix="/uploads", tags=["Uploads"])


def _resolve_playable_url(upload: Upload) -> str | None:
    """
    Public bucket configured -> stable public URL.
    Private bucket (no STORAGE_PUBLIC_BASE_URL set) -> fresh presigned URL, expires in 1hr.
    """
    if not upload.storage_key:
        return None
    if settings.STORAGE_PUBLIC_BASE_URL:
        return f"{settings.STORAGE_PUBLIC_BASE_URL.rstrip('/')}/{upload.storage_key}"
    return generate_presigned_url(upload.storage_key)


def _to_read(upload: Upload) -> UploadRead:
    data = UploadRead.model_validate(upload)
    data.storage_url = _resolve_playable_url(upload)
    return data


@router.post("", response_model=UploadRead, status_code=status.HTTP_201_CREATED)
async def create_upload(
    file: UploadFile = File(...),
    rights_acknowledged: bool = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not rights_acknowledged:
        raise HTTPException(
            status_code=422,
            detail="You must acknowledge you have the rights to this audio before uploading.",
        )

    data = await file.read()
    key, _ = await upload_audio_file(current_user.id, file.filename, file.content_type, data)

    upload = Upload(
        owner_id=current_user.id,
        original_filename=file.filename,
        storage_key=key,
        storage_url=None,  # resolved dynamically on read — see _resolve_playable_url
        rights_acknowledged=rights_acknowledged,
        analysis_status="pending",
    )
    db.add(upload)
    await db.commit()
    await db.refresh(upload)
    return _to_read(upload)


@router.get("", response_model=list[UploadRead])
async def list_my_uploads(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Upload)
        .where(Upload.owner_id == current_user.id)
        .order_by(Upload.created_at.desc())
    )
    return [_to_read(u) for u in result.scalars().all()]


async def _get_owned_upload(upload_id: str, db: AsyncSession, current_user: User) -> Upload:
    result = await db.execute(select(Upload).where(Upload.id == upload_id))
    upload = result.scalar_one_or_none()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    if upload.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your upload")
    return upload


@router.get("/{upload_id}", response_model=UploadRead)
async def get_upload(
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    upload = await _get_owned_upload(upload_id, db, current_user)
    return _to_read(upload)


@router.delete("/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_upload(
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    upload = await _get_owned_upload(upload_id, db, current_user)
    if upload.storage_key:
        await delete_audio_file(upload.storage_key)
    await db.delete(upload)
    await db.commit()
