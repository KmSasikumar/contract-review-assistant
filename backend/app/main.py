"""FastAPI app: Clerk auth on every /api route, CORS for the Vite frontend."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import init_db
from .routers import chat, contracts, reviews
from .routers import settings as settings_router
from .schemas import HealthOut

app = FastAPI(title="Contract Review Assistant", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://contract-review-frontend-455t.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(contracts.router)
app.include_router(reviews.router)
app.include_router(chat.router)
app.include_router(settings_router.router)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/api/health", response_model=HealthOut)
def health():
    return HealthOut(
        ok=True,
        ai_configured=bool(
            settings.gemini_api_key
            or settings.openrouter_api_key
            or settings.groq_api_key
        ),
        auth_configured=bool(settings.clerk_jwks_url),
    )
