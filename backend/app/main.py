"""BeyondMarks API.

One FastAPI service. Routers are added here as their modules land; see
docs/PLAN.md for the order (M3 curriculum, M6 quiz, M10 tutor, M11 chat).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings

app = FastAPI(title="BeyondMarks API", version="0.1.0")

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    """Liveness plus a list of settings that are still empty.

    Render pings this, and during setup it answers the question everyone asks
    first: which key have I not pasted in yet.
    """
    missing = get_settings().missing()
    return {
        "ok": True,
        "service": "beyondmarks-api",
        "configured": not missing,
        "missing_env": missing,
    }
