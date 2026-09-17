import json
import re

import httpx
from fastapi import HTTPException

from app.config import settings

GEMINI_MODEL = "gemini-3.5-flash"
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

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                GEMINI_API_URL,
                params={"key": settings.GEMINI_API_KEY},
                headers={"content-type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": full_prompt}]}],
                },
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timed out waiting for Gemini to respond.")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach Gemini API: {type(e).__name__}: {e}")

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


async def generate_song_concept(prompt: str, genre: str | None = None) -> dict:
    """
    Call Gemini to generate a full song concept: lyrics (with section labels),
    mood, structure outline, and a suggested BPM/key. Returns a dict shaped as
    {"lyrics": str, "bpm": float | None, "musical_key": str | None} ready to
    assign directly onto a Project row.
    """
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="AI song generation is not configured (missing GEMINI_API_KEY).",
        )

    genre_line = f" in the {genre} genre" if genre else ""
    full_prompt = (
        "You are a professional songwriter and music producer. Based on the theme "
        "below, design a complete song concept.\n\n"
        f"Theme{genre_line}: {prompt}\n\n"
        "Respond with ONLY a valid JSON object (no markdown fences, no commentary) "
        "matching exactly this shape:\n"
        "{\n"
        '  "lyrics": "full original lyrics with section labels like [Verse 1], [Chorus], [Bridge]",\n'
        '  "mood": "one short phrase describing the mood/energy",\n'
        '  "structure": ["Verse 1", "Chorus", "Verse 2", "Chorus", "Bridge", "Chorus"],\n'
        '  "suggested_bpm": 96,\n'
        '  "suggested_key": "C# minor"\n'
        "}\n"
        "suggested_bpm must be a plain number. Keep the JSON valid and parseable."
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                GEMINI_API_URL,
                params={"key": settings.GEMINI_API_KEY},
                headers={"content-type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": full_prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json"},
                },
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timed out waiting for Gemini to respond.")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach Gemini API: {type(e).__name__}: {e}")

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"AI provider error: {response.status_code} {response.text}",
        )

    data = response.json()
    try:
        candidates = data["candidates"]
        parts = candidates[0]["content"]["parts"]
        raw_text = "\n".join(part["text"] for part in parts if "text" in part).strip()
    except (KeyError, IndexError):
        raise HTTPException(status_code=502, detail="Unexpected response format from Gemini.")

    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        concept = json.loads(cleaned)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Gemini returned invalid JSON for the song concept.")

    lyrics = str(concept.get("lyrics", "")).strip()
    if not lyrics:
        raise HTTPException(status_code=502, detail="Gemini response was missing lyrics.")

    mood = str(concept.get("mood", "")).strip()
    structure = concept.get("structure") or []
    bpm_raw = concept.get("suggested_bpm")
    key_raw = concept.get("suggested_key")

    header_lines = []
    if mood:
        header_lines.append(f"Mood: {mood}")
    if structure:
        header_lines.append("Structure: " + " \u2192 ".join(str(s) for s in structure))
    full_lyrics = ("\n".join(header_lines) + "\n\n" + lyrics) if header_lines else lyrics

    try:
        bpm = float(bpm_raw) if bpm_raw is not None else None
    except (TypeError, ValueError):
        bpm = None

    musical_key = str(key_raw).strip() if key_raw else None

    return {"lyrics": full_lyrics, "bpm": bpm, "musical_key": musical_key}
