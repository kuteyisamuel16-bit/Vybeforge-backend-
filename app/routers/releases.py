from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, Project, ProjectStatus, Release, ReleaseStatus
from app.schemas import ReleaseSubmit, ReleaseReject, ReleaseRead
from app.auth import get_current_user

router = APIRouter(tags=["Releases"])


async def _get_owned_project(project_id: str, db: AsyncSession, current_user: User) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your project")
    return project


def _require_staff(current_user: User):
    if not current_user.is_staff:
        raise HTTPException(status_code=403, detail="Staff access required.")


@router.post("/projects/{project_id}/release", response_model=ReleaseRead, status_code=status.HTTP_201_CREATED)
async def submit_release(
    project_id: str,
    payload: ReleaseSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _get_owned_project(project_id, db, current_user)

    if not payload.ownership_confirmed:
        raise HTTPException(
            status_code=422,
            detail="You must confirm you own or have the rights to release this work.",
        )

    # basic automated checks before anything reaches human review
    if project.status not in (ProjectStatus.ready, ProjectStatus.published):
        raise HTTPException(
            status_code=422,
            detail="This project isn't ready to submit yet — it needs generated content first.",
        )
    if not project.lyrics or not project.lyrics.strip():
        raise HTTPException(status_code=422, detail="This project has no content to release.")
    if not project.title.strip() or project.title.strip().lower() == "untitled project":
        raise HTTPException(status_code=422, detail="Give this project a real title before releasing it.")

    existing = await db.execute(select(Release).where(Release.project_id == project.id))
    release = existing.scalar_one_or_none()

    if release and release.status in (ReleaseStatus.pending, ReleaseStatus.approved):
        raise HTTPException(
            status_code=409,
            detail=f"This project already has a release {release.status.value}.",
        )

    if release:
        # resubmission after rejection — reuse the row
        release.status = ReleaseStatus.pending
        release.ownership_confirmed = payload.ownership_confirmed
        release.rights_notes = payload.rights_notes
        release.territories = payload.territories
        release.release_date = payload.release_date
        release.rejection_reason = None
        release.reviewed_by = None
        release.reviewed_at = None
    else:
        release = Release(
            project_id=project.id,
            submitted_by=current_user.id,
            status=ReleaseStatus.pending,
            ownership_confirmed=payload.ownership_confirmed,
            rights_notes=payload.rights_notes,
            territories=payload.territories,
            release_date=payload.release_date,
        )
        db.add(release)

    project.status = ProjectStatus.processing  # "under review"
    await db.commit()
    await db.refresh(release)
    return release


@router.get("/projects/{project_id}/release", response_model=ReleaseRead)
async def get_release_status(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _get_owned_project(project_id, db, current_user)
    result = await db.execute(select(Release).where(Release.project_id == project.id))
    release = result.scalar_one_or_none()
    if not release:
        raise HTTPException(status_code=404, detail="No release has been submitted for this project.")
    return release


# ---------- staff review ----------

@router.get("/admin/releases/pending", response_model=list[ReleaseRead])
async def list_pending_releases(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_staff(current_user)
    result = await db.execute(
        select(Release).where(Release.status == ReleaseStatus.pending).order_by(Release.created_at.asc())
    )
    return result.scalars().all()


@router.post("/admin/releases/{release_id}/approve", response_model=ReleaseRead)
async def approve_release(
    release_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_staff(current_user)
    result = await db.execute(select(Release).where(Release.id == release_id))
    release = result.scalar_one_or_none()
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")

    proj_result = await db.execute(select(Project).where(Project.id == release.project_id))
    project = proj_result.scalar_one_or_none()

    release.status = ReleaseStatus.approved
    release.reviewed_by = current_user.id
    release.reviewed_at = datetime.utcnow()
    if project:
        project.status = ProjectStatus.published

    await db.commit()
    await db.refresh(release)
    return release


@router.post("/admin/releases/{release_id}/reject", response_model=ReleaseRead)
async def reject_release(
    release_id: str,
    payload: ReleaseReject,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_staff(current_user)
    result = await db.execute(select(Release).where(Release.id == release_id))
    release = result.scalar_one_or_none()
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")

    proj_result = await db.execute(select(Project).where(Project.id == release.project_id))
    project = proj_result.scalar_one_or_none()

    release.status = ReleaseStatus.rejected
    release.rejection_reason = payload.reason
    release.reviewed_by = current_user.id
    release.reviewed_at = datetime.utcnow()
    if project:
        project.status = ProjectStatus.ready  # back to owner's hands, can edit & resubmit

    await db.commit()
    await db.refresh(release)
    return release
