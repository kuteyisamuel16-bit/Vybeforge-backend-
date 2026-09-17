import uuid
import enum
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Enum, Integer, Float, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class ProjectType(str, enum.Enum):
    ai_song = "ai_song"
    hum_to_melody = "hum_to_melody"
    mouth_to_beat = "mouth_to_beat"
    voice_to_music = "voice_to_music"
    uploaded_edit = "uploaded_edit"
    dj_session = "dj_session"


class ProjectStatus(str, enum.Enum):
    draft = "draft"
    processing = "processing"
    ready = "ready"
    published = "published"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_artist: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    projects: Mapped[list["Project"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    uploads: Mapped[list["Upload"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="Untitled Project")
    project_type: Mapped[ProjectType] = mapped_column(Enum(ProjectType), nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(Enum(ProjectStatus), default=ProjectStatus.draft)
    bpm: Mapped[float] = mapped_column(Float, nullable=True)
    musical_key: Mapped[str] = mapped_column(String(10), nullable=True)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=True) 
    lyrics: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner: Mapped["User"] = relationship(back_populates="projects")
    tracks: Mapped[list["Track"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    project_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    track_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_url: Mapped[str] = mapped_column(String(500), nullable=True)
    volume: Mapped[float] = mapped_column(Float, default=1.0)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project: Mapped["Project"] = relationship(back_populates="tracks")


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=True)
    storage_url: Mapped[str] = mapped_column(String(500), nullable=True)
    rights_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    analysis_status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owner: Mapped["User"] = relationship(back_populates="uploads")
