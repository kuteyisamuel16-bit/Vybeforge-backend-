from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import User, Project, ProjectStatus, Follow, Comment
from app.schemas import UserPublic, ProjectRead, CommentCreate, CommentRead
from app.auth import get_current_user

router = APIRouter(tags=["Community"])


async def _get_user_by_username(username: str, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


async def _counts(user_id: str, db: AsyncSession) -> tuple[int, int]:
    followers = await db.execute(
        select(func.count()).select_from(Follow).where(Follow.following_id == user_id)
    )
    following = await db.execute(
        select(func.count()).select_from(Follow).where(Follow.follower_id == user_id)
    )
    return followers.scalar_one(), following.scalar_one()


def _to_public(user: User, follower_count: int, following_count: int) -> UserPublic:
    return UserPublic(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        is_artist=user.is_artist,
        created_at=user.created_at,
        follower_count=follower_count,
        following_count=following_count,
    )


# ---------- profiles ----------

@router.get("/users/{username}", response_model=UserPublic)
async def get_public_profile(
    username: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = await _get_user_by_username(username, db)
    follower_count, following_count = await _counts(user.id, db)
    return _to_public(user, follower_count, following_count)


@router.get("/users/{username}/projects", response_model=list[ProjectRead])
async def get_public_projects(
    username: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Only PUBLISHED projects are visible here — drafts/ready stay private to the owner."""
    user = await _get_user_by_username(username, db)
    result = await db.execute(
        select(Project)
        .options(selectinload(Project.tracks))
        .where(Project.owner_id == user.id, Project.status == ProjectStatus.published)
        .order_by(Project.updated_at.desc())
    )
    return result.scalars().all()


# ---------- follow system ----------

@router.post("/users/{username}/follow", status_code=status.HTTP_204_NO_CONTENT)
async def follow_user(
    username: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target = await _get_user_by_username(username, db)
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="You can't follow yourself.")
    existing = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id, Follow.following_id == target.id
        )
    )
    if existing.scalar_one_or_none():
        return  # already following — idempotent, no error
    db.add(Follow(follower_id=current_user.id, following_id=target.id))
    await db.commit()


@router.delete("/users/{username}/follow", status_code=status.HTTP_204_NO_CONTENT)
async def unfollow_user(
    username: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target = await _get_user_by_username(username, db)
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id, Follow.following_id == target.id
        )
    )
    follow = result.scalar_one_or_none()
    if follow:
        await db.delete(follow)
        await db.commit()


@router.get("/users/{username}/followers", response_model=list[UserPublic])
async def list_followers(
    username: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = await _get_user_by_username(username, db)
    result = await db.execute(
        select(User).join(Follow, Follow.follower_id == User.id).where(Follow.following_id == user.id)
    )
    out = []
    for f in result.scalars().all():
        fc, fg = await _counts(f.id, db)
        out.append(_to_public(f, fc, fg))
    return out


@router.get("/users/{username}/following", response_model=list[UserPublic])
async def list_following(
    username: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = await _get_user_by_username(username, db)
    result = await db.execute(
        select(User).join(Follow, Follow.following_id == User.id).where(Follow.follower_id == user.id)
    )
    out = []
    for f in result.scalars().all():
        fc, fg = await _counts(f.id, db)
        out.append(_to_public(f, fc, fg))
    return out


# ---------- feedback / comments ----------

async def _get_commentable_project(project_id: str, db: AsyncSession, current_user: User) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status != ProjectStatus.published and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="This project isn't public yet.")
    return project


@router.get("/projects/{project_id}/comments", response_model=list[CommentRead])
async def list_comments(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_commentable_project(project_id, db, current_user)
    result = await db.execute(
        select(Comment, User.username)
        .join(User, Comment.author_id == User.id)
        .where(Comment.project_id == project_id)
        .order_by(Comment.created_at.asc())
    )
    return [
        CommentRead(
            id=c.id,
            project_id=c.project_id,
            author_id=c.author_id,
            author_username=uname,
            body=c.body,
            created_at=c.created_at,
        )
        for c, uname in result.all()
    ]


@router.post(
    "/projects/{project_id}/comments", response_model=CommentRead, status_code=status.HTTP_201_CREATED
)
async def add_comment(
    project_id: str,
    payload: CommentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _get_commentable_project(project_id, db, current_user)
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="Comment can't be empty.")
    comment = Comment(project_id=project.id, author_id=current_user.id, body=body)
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return CommentRead(
        id=comment.id,
        project_id=comment.project_id,
        author_id=comment.author_id,
        author_username=current_user.username,
        body=comment.body,
        created_at=comment.created_at,
    )


@router.delete("/projects/{project_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    project_id: str,
    comment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Comment).where(Comment.id == comment_id, Comment.project_id == project_id)
    )
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    proj_result = await db.execute(select(Project).where(Project.id == project_id))
    project = proj_result.scalar_one_or_none()

    is_author = comment.author_id == current_user.id
    is_owner = project is not None and project.owner_id == current_user.id
    if not is_author and not is_owner:
        raise HTTPException(status_code=403, detail="Not allowed to delete this comment.")

    await db.delete(comment)
    await db.commit()
