import time

import httpx
from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.models import User

router = APIRouter(prefix="/debug", tags=["Debug"])

TEST_HOSTS = {
    "github (known-good baseline)": "https://api.github.com",
    "elevenlabs": "https://api.elevenlabs.io",
    "stability": "https://api.stability.ai",
}


@router.get("/egress-test")
async def egress_test(current_user: User = Depends(get_current_user)):
    """
    TEMPORARY debug route. Tests outbound connectivity to three hosts
    individually so a hang/crash on one doesn't block the others.
    Remove this file + its router registration once the egress issue
    is diagnosed.
    """
    results = {}

    for label, url in TEST_HOSTS.items():
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url)
            results[label] = {
                "outcome": "reached",
                "status_code": resp.status_code,
                "elapsed_seconds": round(time.monotonic() - start, 2),
            }
        except httpx.TimeoutException as e:
            results[label] = {
                "outcome": "timeout",
                "error": str(e),
                "elapsed_seconds": round(time.monotonic() - start, 2),
            }
        except httpx.RequestError as e:
            results[label] = {
                "outcome": "connection_failed",
                "error_type": type(e).__name__,
                "error": str(e),
                "elapsed_seconds": round(time.monotonic() - start, 2),
            }
        except Exception as e:
            results[label] = {
                "outcome": "unexpected_exception",
                "error_type": type(e).__name__,
                "error": str(e),
                "elapsed_seconds": round(time.monotonic() - start, 2),
            }

    return results
