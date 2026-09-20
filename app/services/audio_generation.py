import httpx
from fastapi import HTTPException

from app.config import settings

ELEVENLABS_MUSIC_URL = "https://api.elevenlabs.io/v1/music"
STABILITY_BASE_URL = "https://api.stability.ai"


async def generate_vocal_song(
    lyrics: str,
    style: str | None = None,
    duration_ms: int | None = None,
) -> bytes:
    """
    Renders a full sung track from lyrics via ElevenLabs Music.

    Request shape: POST /v1/music, `xi-api-key` header, `Accept: audio/mpeg`
    returns raw audio bytes directly (no polling needed — this call blocks
    until the render is done). Source: elevenlabs.io/docs/api-reference/music/compose.
    Whether the model sings the supplied lyrics verbatim vs. treats them as
    inspiration hasn't been verified against a real account yet — test with
    a short generation first and adjust the prompt wording below if needed.
    """
    if not settings.ELEVENLABS_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Vocal song generation is not configured (missing ELEVENLABS_API_KEY).",
        )

    style_line = f" Style: {style}." if style else ""
    prompt = (
        "Perform and produce a full song using these lyrics exactly as written, "
        "with vocals, instrumentation and structure matching the section labels "
        f"(e.g. [Verse 1], [Chorus], [Bridge]).{style_line}\n\n{lyrics}"
    )

    body = {"prompt": prompt, "model_id": "music_v1"}
    if duration_ms:
        body["music_length_ms"] = max(3000, min(duration_ms, 600000))

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                ELEVENLABS_MUSIC_URL,
                headers={
                    "xi-api-key": settings.ELEVENLABS_API_KEY,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json=body,
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timed out waiting for ElevenLabs to render the song.")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach ElevenLabs: {type(e).__name__}: {e}")

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"ElevenLabs Music error: {response.status_code} {response.text[:300]}",
        )

    return response.content


async def generate_instrumental(prompt: str, duration_seconds: int = 30) -> bytes:
    """
    Renders an instrumental-only track from a text prompt via Stability AI's
    Stable Audio model (no vocals — Stable Audio explicitly can't sing).

    This is SYNCHRONOUS (no job queue, no polling) and uses multipart/form-data,
    confirmed directly from Stability's own official API reference example at
    platform.stability.ai/docs/api-reference:

        requests.post(
            "https://api.stability.ai/v2beta/audio/stable-audio-2/text-to-audio",
            headers={"authorization": f"Bearer sk-...", "accept": "audio/*"},
            files={"none": ""},
            data={"prompt": ..., "output_format": "mp3", "duration": 20, "model": "stable-audio-2.5"},
        )

    Note the path says "stable-audio-2" while the actual model tier is chosen
    via the "model" field in the form data ("stable-audio-2.5" here) — that's
    not a typo, it's how Stability's own docs show it.
    """
    if not settings.STABILITY_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Instrumental generation is not configured (missing STABILITY_API_KEY).",
        )

    duration_seconds = max(1, min(duration_seconds, 190))

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{STABILITY_BASE_URL}/v2beta/audio/stable-audio-2/text-to-audio",
                headers={
                    "authorization": f"Bearer {settings.STABILITY_API_KEY}",
                    "accept": "audio/*",
                },
                files={"none": ""},  # required to force multipart encoding, per Stability's docs
                data={
                    "prompt": prompt,
                    "output_format": "mp3",
                    "duration": duration_seconds,
                    "model": "stable-audio-2.5",
                },
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timed out waiting for Stability AI to render the instrumental.")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach Stability AI: {type(e).__name__}: {e}")

    if response.status_code != 200:
        raise HTTPException(
            status_code=502, detail=f"Stability AI error: {response.status_code} {response.text[:300]}"
        )

    return response.content
