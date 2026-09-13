from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import User, Project, Track
from app.schemas import ProjectCreate, ProjectRead, ProjectUpdate, TrackCreate, TrackRead
from app.auth import get_current_user

router = APIRouter(prefix="/projects", tags=["Projects"])


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
    return project


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
    return result.scalars().all()


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
    return await _get_owned_project(project_id, db, current_user)


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: str,
    payload: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _get_owned_project(project_id, db, current_user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    await db.commit()
    await db.refresh(project, attribute_names=["tracks"])
    return project


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
    return track
