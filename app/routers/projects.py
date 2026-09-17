from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models import User, Project, Track, ProjectStatus
from app.schemas import ProjectCreate, ProjectRead, ProjectUpdate, TrackCreate, TrackRead, TrackUpdate
from app.auth import get_current_user
from app.services.ai import generate_lyrics, generate_song_concept
from app.services.storage import generate_presigned_url

router = APIRouter(prefix="/projects", tags=["Projects"])


def _resolve_track_url(track: Track) -> Optional[str]:
    """
    Track.file_url stores a storage KEY, not a playable URL (same private-bucket
    situation as Upload.storage_key — see app/routers/uploads.py). Resolve it to
    a public URL if one's configured, otherwise a fresh presigned URL.
    """
    if not track.file_url:
        return None
    if settings.STORAGE_PUBLIC_BASE_URL:
        return f"{settings.STORAGE_PUBLIC_BASE_URL.rstrip('/')}/{track.file_url}"
    return generate_presigned_url(track.file_url)


def _track_to_read(track: Track) -> TrackRead:
    return TrackRead(
        id=track.id,
        name=track.name,
        track_type=track.track_type,
        file_url=_resolve_track_url(track),
        volume=track.volume,
        order_index=track.order_index,
    )


def _project_to_read(project: Project) -> ProjectRead:
    data = ProjectRead.model_validate(project)
    data.tracks = [_track_to_read(t) for t in project.tracks]
    return data


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = Project(owner_id=current_user.id, **payload.model_dump())
    db.add(project)
    await db.commit()
    await db.refresh(project, attribute_names=["tracks"])
    return _project_to_read(project)


@router.get("", response_model=list[ProjectRead])
async def list_my_projects(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Project)
        .options(selectinload(Project.tracks))
        .where(Project.owner_id == current_user.id)
        .order_by(Project.updated_at.desc())
    )
    return [_project_to_read(p) for p in result.scalars().all()]


async def _get_owned_project(project_id: str, db: AsyncSession, current_user: User) -> Project:
    result = await db.execute(
        select(Project).options(selectinload(Project.tracks)).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your project")
    return project


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _get_owned_project(project_id, db, current_user)
    return _project_to_read(project)


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: str,
    payload: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _get_owned_project(project_id, db, current_user)
    updates = payload.model_dump(exclude_unset=True)
    if "status" in updates and updates["status"] in (ProjectStatus.published, ProjectStatus.processing):
        raise HTTPException(
            status_code=422,
            detail="Use the release endpoint to submit for review — status can't be set directly.",
        )
    for field, value in updates.items():
        setattr(project, field, value)
    await db.commit()
    await db.refresh(project, attribute_names=["tracks"])
    return _project_to_read(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _get_owned_project(project_id, db, current_user)
    await db.delete(project)
    await db.commit()


@router.post("/{project_id}/tracks", response_model=TrackRead, status_code=status.HTTP_201_CREATED)
async def add_track(
    project_id: str,
    payload: TrackCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _get_owned_project(project_id, db, current_user)
    track = Track(project_id=project.id, **payload.model_dump())
    db.add(track)
    await db.commit()
    await db.refresh(track)
    return _track_to_read(track)


@router.delete("/{project_id}/tracks/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_track(
    project_id: str,
    track_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _get_owned_project(project_id, db, current_user)
    track = next((t for t in project.tracks if t.id == track_id), None)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")
    await db.delete(track)
    await db.commit()


@router.patch("/{project_id}/tracks/{track_id}", response_model=TrackRead)
async def update_track(
    project_id: str,
    track_id: str,
    payload: TrackUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _get_owned_project(project_id, db, current_user)
    track = next((t for t in project.tracks if t.id == track_id), None)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(track, field, value)
    await db.commit()
    await db.refresh(track)
    return _track_to_read(track)


class LyricsRequest(BaseModel):
    prompt: str
    genre: Optional[str] = None


@router.post("/{project_id}/generate/lyrics", response_model=ProjectRead)
async def generate_project_lyrics(
    project_id: str,
    payload: LyricsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _get_owned_project(project_id, db, current_user)
    lyrics = await generate_lyrics(payload.prompt, payload.genre)
    project.lyrics = lyrics
    project.status = ProjectStatus.ready
    await db.commit()
    await db.refresh(project, attribute_names=["tracks"])
    return _project_to_read(project)


@router.post("/{project_id}/generate/concept", response_model=ProjectRead)
async def generate_project_concept(
    project_id: str,
    payload: LyricsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a full song concept: lyrics + mood/structure header + suggested bpm/key."""
    project = await _get_owned_project(project_id, db, current_user)
    concept = await generate_song_concept(payload.prompt, payload.genre)
    project.lyrics = concept["lyrics"]
    project.bpm = concept["bpm"]
    project.musical_key = concept["musical_key"]
    project.status = ProjectStatus.ready
    await db.commit()
    await db.refresh(project, attribute_names=["tracks"])
    return _project_to_read(project)
