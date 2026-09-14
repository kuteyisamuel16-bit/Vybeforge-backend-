import httpx
from fastapi import HTTPException

from app.config import settings

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
)


async def generate_lyrics(prompt: str, genre: str | None = None) -> str:
    """Call Gemini to generate song lyrics from a theme/prompt + optional genre."""
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="AI lyrics generation is not configured (missing GEMINI_API_KEY).",
        )

    genre_line = f" in the {genre} genre" if genre else ""
    full_prompt = (
        "You are a professional songwriter. Write complete, original song lyrics "
        "with a clear structure (verse, chorus, verse, chorus, bridge, chorus). "
        "Return only the lyrics themselves, no commentary or explanation.\n\n"
        f"Write song lyrics{genre_line} about: {prompt}"
    )

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            GEMINI_API_URL,
            params={"key": settings.GEMINI_API_KEY},
            headers={"content-type": "application/json"},
            json={
                "contents": [{"parts": [{"text": full_prompt}]}],
            },
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"AI provider error: {response.status_code} {response.text}",
        )

    data = response.json()
    try:
        candidates = data["candidates"]
        parts = candidates[0]["content"]["parts"]
        return "\n".join(part["text"] for part in parts if "text" in part).strip()
    except (KeyError, IndexError):
        raise HTTPException(status_code=502, detail="Unexpected response format from Gemini.")
