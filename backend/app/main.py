from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .admin import router as admin_router
from .companies import router as companies_router
from .config import get_settings
from .jobs import mark_interrupted_runs, router as jobs_router
from .supabase import close_http_client
from .users import router as users_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await mark_interrupted_runs(get_settings())
    yield
    await close_http_client()


settings = get_settings()
app = FastAPI(
    title="Funding Radar API",
    version="2.0.0",
    description=(
        "Startup funding data: authenticated company search with rich filters, per-user notes and "
        "viewed status, admin data management, and background scraping/enrichment jobs."
    ),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(users_router)
app.include_router(companies_router)
app.include_router(admin_router)
app.include_router(jobs_router)


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "service": "funding-radar-api"}
