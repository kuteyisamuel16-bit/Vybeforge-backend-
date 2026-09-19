from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import uploads
from app.routers import community
from app.routers import audio
from app.routers import debug
from app.database import engine, Base
from app.routers import auth, projects
from app import models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="VYBEFORGE API",
    description="Foundation API: accounts, projects, tracks — Make What You Hear.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this to your app domains before launch
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(uploads.router)
app.include_router(community.router)
app.include_router(audio.router)
app.include_router(debug.router)
@app.get("/")
async def root():
    return {"message": "VYBEFORGE API is running. Make what you hear."}


@app.get("/health")
async def health():
    return {"status": "ok"}
