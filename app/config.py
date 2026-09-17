from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    GEMINI_API_KEY: str = ""

    # Object storage (S3-compatible: AWS S3, Cloudflare R2, Backblaze B2, etc.)
    STORAGE_ENDPOINT_URL: str = ""       # leave blank for real AWS S3
    STORAGE_ACCESS_KEY_ID: str = ""
    STORAGE_SECRET_ACCESS_KEY: str = ""
    STORAGE_BUCKET_NAME: str = ""
    STORAGE_REGION: str = "auto"
    STORAGE_PUBLIC_BASE_URL: str = ""    # public base URL to serve uploaded files from

    class Config:
        env_file = ".env"


settings = Settings()
