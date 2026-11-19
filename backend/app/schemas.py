from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


Role = Literal["admin", "user"]
EnrichTarget = Literal["never", "missing_website", "missing_founded", "careers_unchecked", "stale", "all"]
EarlyStageType = Literal["pre-seed", "bootstrapped", "pre-funding", "ideation", "self-funded"]


class UserContext(BaseModel):
    id: str
    email: str
    role: Role


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class CompanyFields(BaseModel):
    """Fields an administrator may set on a company."""

    name: str | None = Field(default=None, min_length=1, max_length=300)
    website: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=10_000)
    location: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=120)
    is_remote: bool | None = None
    industry: str | None = Field(default=None, max_length=120)
    subindustry: str | None = Field(default=None, max_length=200)
    entity_kind: Literal["startup", "investment_vehicle", "real_estate", "other"] | None = None
    founded_year: int | None = Field(default=None, ge=1800, le=2100)
    founded_on: date | None = None
    employee_count: int | None = Field(default=None, ge=0, le=10_000_000)
    status: str | None = Field(default=None, max_length=80)
    stage: str | None = Field(default=None, max_length=80)
    accelerator_batch: str | None = Field(default=None, max_length=80)
    is_hiring: bool | None = None
    careers_url: str | None = Field(default=None, max_length=500)
    has_careers_page: bool | None = None
    open_jobs_count: int | None = Field(default=None, ge=0, le=100_000)

    _strip = field_validator(
        "name", "website", "description", "location", "city", "state", "country", "industry",
        "subindustry", "status", "stage", "accelerator_batch", "careers_url", mode="before",
    )(_blank_to_none)


class CompanyCreate(CompanyFields):
    name: str = Field(min_length=1, max_length=300)


class CompanyUpdate(CompanyFields):
    pass


class FundingRoundFields(BaseModel):
    announced_on: date | None = None
    round_type: str | None = Field(default=None, max_length=120)
    amount: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
    amount_usd: float | None = Field(default=None, ge=0)
    investors: list[str] | None = None
    title: str | None = Field(default=None, max_length=500)
    summary: str | None = Field(default=None, max_length=10_000)
    source_url: str | None = Field(default=None, max_length=1000)

    _strip = field_validator("round_type", "currency", "title", "summary", "source_url", mode="before")(_blank_to_none)


class FundingRoundCreate(FundingRoundFields):
    company_id: str


class FundingRoundUpdate(FundingRoundFields):
    pass


class NoteInput(BaseModel):
    note: str = Field(max_length=20_000)


class ViewInput(BaseModel):
    viewed: bool = True


class BulkViewInput(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    viewed: bool = True


class BulkDeleteInput(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)


class RoleInput(BaseModel):
    role: Role


class CollectJobInput(BaseModel):
    sources: list[Literal[
        "sec", "rss", "yc", "producthunt", "betalist", "antler", "ef", "techstars", "wellfound"
    ]] = Field(
        default_factory=lambda: [
            "rss", "yc", "producthunt", "betalist", "antler", "ef", "techstars", "wellfound"
        ],
        min_length=1,
    )
    sec_quarters: int = Field(default=1, ge=1, le=40)
    limit: int | None = Field(default=None, ge=1, le=100_000)
    include_funds: bool = False
    enrich_after: bool = True
    enrich_limit: int = Field(default=200, ge=0, le=20_000)
    enrich_target: EnrichTarget = "never"
    funding_types: list[EarlyStageType] = Field(default_factory=list)


class EnrichJobInput(BaseModel):
    target: EnrichTarget = "missing_website"
    limit: int = Field(default=500, ge=1, le=20_000)
    only_startups: bool = True
    sources: list[str] = Field(default_factory=list)
    ids: list[str] = Field(default_factory=list, max_length=2_000)
