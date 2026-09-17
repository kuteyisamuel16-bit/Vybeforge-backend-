from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Upload, User
from app.schemas import UploadRead
from app.auth import get_current_user
from app.services.storage import delete_audio_file, upload_audio_file

router = APIRouter(prefix="/uploads", tags=["Uploads"])


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
    key, public_url = await upload_audio_file(
        current_user.id, file.filename, file.content_type, data
    )

    upload = Upload(
        owner_id=current_user.id,
        original_filename=file.filename,
        storage_key=key,
        storage_url=public_url,
        rights_acknowledged=rights_acknowledged,
        analysis_status="pending",
    )
    db.add(upload)
    await db.commit()
    await db.refresh(upload)
    return upload


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
    return result.scalars().all()


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
    return await _get_owned_upload(upload_id, db, current_user)


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
  
