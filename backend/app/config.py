from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]
# Later files win: backend/.env overrides the repo-root .env (shared with the collector CLI).
ENV_FILES = (BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env")


class Settings(BaseSettings):
    supabase_url: str
    supabase_anon_key: str | None = None
    supabase_service_role_key: str = Field(
        validation_alias=AliasChoices("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY")
    )
    sec_user_agent: str = "StartupFundingCollector/1.0 admin@example.com"
    enrich_user_agent: str = "Mozilla/5.0 (compatible; FundingRadarBot/1.0)"
    # Optional: official Brave Search API key, used only as a last-resort website finder.
    brave_search_api_key: str | None = None
    # Comma-separated emails that are always administrators (bootstrap for the first admin).
    admin_emails: str = ""
    frontend_origins: str = "http://localhost:3000,http://localhost:5173"
    enrich_workers: int = Field(default=6, ge=1, le=24)

    model_config = SettingsConfigDict(env_file=ENV_FILES, extra="ignore")

    @model_validator(mode="after")
    def reject_example_values(self) -> "Settings":
        """Fail fast when a value was copied unchanged from an .env.example file."""
        values = {
            "SUPABASE_URL": self.supabase_url,
            "SUPABASE_SERVICE_ROLE_KEY": self.supabase_service_role_key,
            "SUPABASE_ANON_KEY": self.supabase_anon_key or "",
        }
        leftovers = [name for name, value in values.items() if "your-" in value or "your_" in value]
        if leftovers:
            raise ValueError(
                f"{', '.join(leftovers)} still contain the example placeholder. Put your real Supabase values in "
                f"{ENV_FILES[1]} (or {ENV_FILES[0]})."
            )
        return self

    @property
    def allowed_origins(self) -> list[str]:
        return [item.strip() for item in self.frontend_origins.split(",") if item.strip()]

    @property
    def admin_email_set(self) -> set[str]:
        return {item.strip().lower() for item in self.admin_emails.split(",") if item.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
