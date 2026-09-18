import asyncio

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

    Uses Stability's async job pattern: submit -> poll -> fetch. Assembled
    from third-party mirrors of Stability's docs (aimlapi.com, api-evangelist)
    since the primary platform.stability.ai reference page wasn't directly
    fetchable during development — verify the exact `model` id string
    against your own Stability dashboard before relying on this in
    production. Set to the Stable Audio 3 (medium, distilled/production)
    checkpoint per the account's confirmed access — "stable-audio-3-medium".
    If Stability's hosted API expects a different exact string for this
    tier (e.g. just "stable-audio-3"), check the dashboard/API reference
    and update the constant below.
    """
    if not settings.STABILITY_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Instrumental generation is not configured (missing STABILITY_API_KEY).",
        )

    duration_seconds = max(1, min(duration_seconds, 380))
    headers = {
        "Authorization": f"Bearer {settings.STABILITY_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            submit = await client.post(
                f"{STABILITY_BASE_URL}/v2/generate/audio",
                headers=headers,
                json={
                    "model": "stable-audio-3-medium",
                    "prompt": prompt,
                    "seconds_total": duration_seconds,
                },
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timed out submitting the instrumental job to Stability AI.")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach Stability AI: {type(e).__name__}: {e}")

    if submit.status_code not in (200, 201, 202):
        raise HTTPException(
            status_code=502, detail=f"Stability AI error: {submit.status_code} {submit.text[:300]}"
        )

    job = submit.json()
    generation_id = job.get("id")
    if not generation_id:
        raise HTTPException(status_code=502, detail="Stability AI response was missing a generation id.")

    async with httpx.AsyncClient(timeout=30.0) as client:
        for _ in range(30):  # poll for up to ~60s
            await asyncio.sleep(2)
            poll = await client.get(
                f"{STABILITY_BASE_URL}/v2/generate/audio",
                headers=headers,
                params={"generation_id": generation_id},
            )
            if poll.status_code != 200:
                continue
            result = poll.json()
            status_value = result.get("status")

            if status_value == "completed":
                audio_url = result.get("audio_url") or result.get("url")
                if audio_url:
                    audio_resp = await client.get(audio_url)
                    if audio_resp.status_code != 200:
                        raise HTTPException(
                            status_code=502, detail="Could not download the finished audio from Stability AI."
                        )
                    return audio_resp.content
                content_type = poll.headers.get("content-type", "")
                if content_type.startswith("audio/"):
                    return poll.content
                raise HTTPException(
                    status_code=502, detail="Stability AI marked the job complete but returned no audio."
                )

            if status_value == "failed":
                raise HTTPException(status_code=502, detail="Stability AI reported the generation failed.")

    raise HTTPException(status_code=504, detail="Timed out waiting for Stability AI to finish generating audio.")
