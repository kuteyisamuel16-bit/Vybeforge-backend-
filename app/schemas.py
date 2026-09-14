from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr

from app.models import ProjectType, ProjectStatus


class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str
    display_name: Optional[str] = None


class UserRead(BaseModel):
    id: str
    email: EmailStr
    username: str
    display_name: Optional[str] = None
    is_artist: bool
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TrackCreate(BaseModel):
    name: str
    track_type: str
    file_url: Optional[str] = None
    volume: float = 1.0
    order_index: int = 0


class TrackRead(BaseModel):
    id: str
    name: str
    track_type: str
    file_url: Optional[str] = None
    volume: float
    order_index: int

    class Config:
        from_attributes = True


class ProjectCreate(BaseModel):
    title: str = "Untitled Project"
    project_type: ProjectType
    prompt_text: Optional[str] = None
    bpm: Optional[float] = None
    musical_key: Optional[str] = None


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[ProjectStatus] = None
    bpm: Optional[float] = None
    musical_key: Optional[str] = None


class ProjectRead(BaseModel):
    id: str
    owner_id: str
    title: str
    project_type: ProjectType
    status: ProjectStatus
    bpm: Optional[float] = None
    musical_key: Optional[str] = None
    prompt_text: Optional[str] = None
    lyrics: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    tracks: list[TrackRead] = []

    class Config:
        from_attributes = True
