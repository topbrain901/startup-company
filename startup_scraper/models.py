from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Company:
    """A company row as reported by a source.

    Enrichment-owned columns (careers, website verification, ...) are deliberately absent:
    a re-scrape must never erase what enrichment or an administrator added.
    """

    source_key: str
    source_name: str
    source_id: str
    source_url: str
    name: str
    normalized_name: str
    website: str | None = None
    domain: str | None = None
    description: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    location: str | None = None
    is_remote: bool | None = None
    industry: str | None = None
    subindustry: str | None = None
    entity_kind: str | None = None
    founded_year: int | None = None
    founded_on: str | None = None
    founded_source: str | None = None
    employee_count: int | None = None
    status: str | None = None
    accelerator_batch: str | None = None
    stage: str | None = None
    is_hiring: bool | None = None
    logo_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    first_seen_at: str = field(default_factory=utc_now)
    last_seen_at: str = field(default_factory=utc_now)

    def row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FundingRound:
    source_key: str
    company_source_key: str
    source_name: str
    source_url: str
    announced_on: date | None = None
    round_type: str | None = None
    amount: float | None = None
    currency: str | None = None
    amount_usd: float | None = None
    valuation: float | None = None
    valuation_currency: str | None = None
    valuation_usd: float | None = None
    investors: list[str] = field(default_factory=list)
    title: str | None = None
    summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    first_seen_at: str = field(default_factory=utc_now)
    last_seen_at: str = field(default_factory=utc_now)

    def row(self) -> dict[str, Any]:
        result = asdict(self)
        result["announced_on"] = self.announced_on.isoformat() if self.announced_on else None
        return result
