from __future__ import annotations

import csv
import io
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .auth import current_user
from .config import Settings, get_settings
from .schemas import BulkViewInput, NoteInput, UserContext, ViewInput
from .supabase import SupabaseAPI, eq, in_filter


router = APIRouter(prefix="/companies", tags=["companies"])

YesNo = Literal["", "yes", "no"]
Sort = Literal["funded", "amount", "total", "valuation", "added", "name", "founded_desc", "founded_asc", "team", "jobs"]
EXPORT_LIMIT = 5000
_facets_cache: tuple[float, Any] | None = None


def valid_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise HTTPException(404, "Company not found") from exc


def search_params(
    q: str = Query("", max_length=200, description="Name, description, domain, location, industry, or investor"),
    location: str = Query("", max_length=120, description="City/state/country contains"),
    country: list[str] = Query(default=[]),
    state: list[str] = Query(default=[]),
    industry: list[str] = Query(default=[]),
    sector: list[str] = Query(default=[], description="Cross-source sector, e.g. 'Fintech', 'AI & machine learning'"),
    investor: str = Query("", max_length=120, description="Any recorded investor contains"),
    stage: list[str] = Query(default=[]),
    company_status: list[str] = Query(default=[], alias="status"),
    source: list[str] = Query(default=[]),
    batch: list[str] = Query(default=[]),
    kind: list[str] = Query(default=[], description="startup, investment_vehicle, real_estate, other"),
    round_type: list[str] = Query(default=[]),
    provider: list[str] = Query(default=[], description="Careers provider: website, greenhouse, lever, ashby, yc, ..."),
    website_status: list[str] = Query(default=[]),
    founded_source: list[str] = Query(default=[]),
    remote: YesNo = "",
    website: YesNo = "",
    careers: Literal["", "yes", "no", "unchecked"] = "",
    hiring: YesNo = "",
    email: YesNo = "",
    linkedin: YesNo = "",
    viewed: YesNo = "",
    notes: YesNo = "",
    founded_known: YesNo = "",
    enriched: YesNo = "",
    min_jobs: int | None = Query(None, ge=0, le=100_000),
    amount_min: float | None = Query(None, ge=0),
    amount_max: float | None = Query(None, ge=0),
    total_min: float | None = Query(None, ge=0),
    total_max: float | None = Query(None, ge=0),
    valuation_min: float | None = Query(None, ge=0, description="Most recent known valuation at least (USD)"),
    funded_within: int | None = Query(None, ge=1, le=36_500, description="Latest round within N days"),
    funded_after: date | None = None,
    funded_before: date | None = None,
    founded_from: int | None = Query(None, ge=1800, le=2100),
    founded_to: int | None = Query(None, ge=1800, le=2100),
    team_min: int | None = Query(None, ge=0),
    team_max: int | None = Query(None, ge=0),
    added_within: int | None = Query(None, ge=1, le=36_500, description="Discovered within N days"),
    sort: Sort = "funded",
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "q": q.strip(), "location": location.strip(), "countries": country, "states": state,
        "industries": industry, "sectors": sector, "investor": investor.strip(), "stages": stage, "statuses": company_status, "sources": source,
        "batches": batch, "kinds": kind, "round_types": round_type, "providers": provider,
        "website_statuses": website_status, "founded_sources": founded_source,
        "remote": remote, "website": website, "careers": careers, "hiring": hiring, "email": email, "linkedin": linkedin, "viewed": viewed,
        "notes": notes, "founded_known": founded_known, "enriched": enriched, "min_jobs": min_jobs,
        "amount_min": amount_min, "amount_max": amount_max, "total_min": total_min, "total_max": total_max,
        "valuation_min": valuation_min,
        "funded_after": funded_after.isoformat() if funded_after else None,
        "funded_before": funded_before.isoformat() if funded_before else None,
        "founded_from": founded_from, "founded_to": founded_to, "team_min": team_min, "team_max": team_max,
        "sort": sort,
    }
    if funded_within:
        cutoff = date.today() - timedelta(days=funded_within)
        if not funded_after or cutoff > funded_after:
            params["funded_after"] = cutoff.isoformat()
    if added_within:
        params["added_after"] = (datetime.now(timezone.utc) - timedelta(days=added_within)).isoformat()
    return {key: value for key, value in params.items() if value not in ("", None, [])}


@router.get("")
async def list_companies(
    params: dict[str, Any] = Depends(search_params),
    page: int = Query(1, ge=1, le=100_000),
    page_size: int = Query(25, ge=1, le=200),
    user: UserContext = Depends(current_user),
    settings: Settings = Depends(get_settings),
):
    result = await SupabaseAPI(settings).rpc(
        "search_companies",
        {"p_user_id": user.id, "p": {**params, "limit": page_size, "offset": (page - 1) * page_size}},
    )
    total = int(result.get("total") or 0)
    return {
        "companies": result.get("rows") or [],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


EXPORT_COLUMNS = (
    ("name", "Company"), ("website", "Website"), ("has_careers_page", "Careers page"), ("careers_url", "Careers URL"),
    ("careers_provider", "Careers provider"), ("open_jobs_count", "Open jobs"), ("location", "Location"),
    ("city", "City"), ("state", "State"), ("country", "Country"), ("is_remote", "Remote"), ("industry", "Industry"),
    ("stage", "Stage"), ("status", "Status"), ("entity_kind", "Company type"), ("founded_year", "Founded"),
    ("founded_source", "Founded source"), ("latest_round_type", "Latest round"), ("latest_round_on", "Latest round date"),
    ("latest_amount_usd", "Latest amount (USD)"), ("total_funding_usd", "Total raised (USD)"),
    ("latest_valuation_usd", "Latest valuation (USD)"), ("investors", "Investors"), ("sectors", "Sectors"),
    ("employee_count", "Team size"), ("contact_email", "Contact email"), ("linkedin_url", "LinkedIn"),
    ("twitter_url", "X / Twitter"), ("github_url", "GitHub"), ("source_name", "Source"), ("source_url", "Source URL"),
    ("viewed", "Viewed"), ("note", "My note"),
)


def csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    return value


@router.get("/export", response_class=Response)
async def export_companies(
    params: dict[str, Any] = Depends(search_params),
    user: UserContext = Depends(current_user),
    settings: Settings = Depends(get_settings),
):
    """CSV of the companies matching the current filters (up to 5,000 rows)."""
    result = await SupabaseAPI(settings).rpc(
        "search_companies", {"p_user_id": user.id, "p": {**params, "limit": EXPORT_LIMIT, "offset": 0}}
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([label for _, label in EXPORT_COLUMNS])
    for row in result.get("rows") or []:
        writer.writerow([csv_value(row.get(key)) for key, _ in EXPORT_COLUMNS])
    filename = f"companies-{date.today().isoformat()}.csv"
    return Response(
        content="﻿" + buffer.getvalue(),  # BOM so Excel opens UTF-8 correctly
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/facets")
async def facets(user: UserContext = Depends(current_user), settings: Settings = Depends(get_settings)):
    """Distinct filter values with counts."""
    global _facets_cache
    if _facets_cache and _facets_cache[0] > time.monotonic():
        return _facets_cache[1]
    data = await SupabaseAPI(settings).rpc("company_facets", {})
    _facets_cache = (time.monotonic() + 60, data)
    return data


def invalidate_facets() -> None:
    global _facets_cache
    _facets_cache = None


async def company_detail(api: SupabaseAPI, company_id: str, user_id: str) -> dict[str, Any]:
    rows, _ = await api.select(
        "startup_companies",
        f"select=*,funding_rounds(*)&id={eq(company_id)}&funding_rounds.order=announced_on.desc.nullslast&limit=1",
    )
    if not rows:
        raise HTTPException(404, "Company not found")
    company = rows[0]
    notes, _ = await api.select(
        "company_notes", f"select=note,updated_at&company_id={eq(company_id)}&user_id={eq(user_id)}&limit=1"
    )
    views, _ = await api.select(
        "company_views", f"select=viewed,viewed_at&company_id={eq(company_id)}&user_id={eq(user_id)}&limit=1"
    )
    company["note"] = notes[0]["note"] if notes else ""
    company["note_updated_at"] = notes[0]["updated_at"] if notes else None
    company["viewed"] = bool(views and views[0]["viewed"])
    company["viewed_at"] = views[0]["viewed_at"] if views else None
    return company


@router.get("/{company_id}")
async def get_company(company_id: str, user: UserContext = Depends(current_user), settings: Settings = Depends(get_settings)):
    return await company_detail(SupabaseAPI(settings), valid_id(company_id), user.id)


@router.put("/{company_id}/note")
async def save_note(
    company_id: str, payload: NoteInput, user: UserContext = Depends(current_user), settings: Settings = Depends(get_settings)
):
    """Each user keeps a private note per company. An empty note deletes it."""
    api = SupabaseAPI(settings)
    company_id = valid_id(company_id)
    if not payload.note.strip():
        await api.delete("company_notes", f"company_id={eq(company_id)}&user_id={eq(user.id)}")
        return {"note": "", "updated_at": None}
    rows = await api.insert(
        "company_notes", {"company_id": company_id, "user_id": user.id, "note": payload.note}, upsert="company_id,user_id"
    )
    return {"note": rows[0]["note"], "updated_at": rows[0]["updated_at"]}


@router.put("/{company_id}/view")
async def set_view(
    company_id: str, payload: ViewInput, user: UserContext = Depends(current_user), settings: Settings = Depends(get_settings)
):
    """Mark a company viewed / not viewed for the current user."""
    company_id = valid_id(company_id)
    viewed_at = datetime.now(timezone.utc).isoformat() if payload.viewed else None
    rows = await SupabaseAPI(settings).insert(
        "company_views",
        {"company_id": company_id, "user_id": user.id, "viewed": payload.viewed, "viewed_at": viewed_at},
        upsert="company_id,user_id",
    )
    return {"company_id": company_id, "viewed": rows[0]["viewed"], "viewed_at": rows[0]["viewed_at"]}


@router.post("/views")
async def set_views(payload: BulkViewInput, user: UserContext = Depends(current_user), settings: Settings = Depends(get_settings)):
    """Mark many companies viewed / not viewed at once."""
    ids = list(dict.fromkeys(valid_id(item) for item in payload.ids))
    api = SupabaseAPI(settings)
    existing, _ = await api.select("startup_companies", f"select=id&id={in_filter(ids)}")
    ids = [row["id"] for row in existing]
    if ids:
        viewed_at = datetime.now(timezone.utc).isoformat() if payload.viewed else None
        await api.insert(
            "company_views",
            [{"company_id": item, "user_id": user.id, "viewed": payload.viewed, "viewed_at": viewed_at} for item in ids],
            upsert="company_id,user_id",
        )
    return {"updated": len(ids), "viewed": payload.viewed}
