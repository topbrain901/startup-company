from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response

from startup_scraper.contacts import EMAIL_RE, github_url, linkedin_url, twitter_url
from startup_scraper.enrichment import Enricher
from startup_scraper.supabase import SupabaseStore
from startup_scraper.util import canonical_url, domain_from_url, normalize_name

from .auth import admin_user, forget_user
from .companies import company_detail, invalidate_facets, valid_id
from .config import Settings, get_settings
from .schemas import (
    BulkDeleteInput,
    CompanyCreate,
    CompanyFields,
    CompanyUpdate,
    FundingRoundCreate,
    FundingRoundUpdate,
    RoleInput,
    UserContext,
)
from .supabase import SupabaseAPI, eq, in_filter


router = APIRouter(prefix="/admin", tags=["admin"])

# Editing one field also pins the columns derived from it, so neither a re-scrape nor
# enrichment can make them disagree.
DERIVED_FIELDS = {
    "name": ["normalized_name"],
    "website": ["domain", "website_status", "website_discovery_source", "website_verified_at"],
    "founded_year": ["founded_on", "founded_source"],
    "founded_on": ["founded_source"],
    "has_careers_page": ["careers_url", "careers_provider", "open_jobs_count", "careers_checked_at"],
    "careers_url": ["has_careers_page", "careers_provider", "open_jobs_count", "careers_checked_at"],
    "open_jobs_count": ["has_careers_page", "careers_url", "careers_provider", "careers_checked_at"],
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def curated_changes(changes: dict[str, Any]) -> dict[str, Any]:
    """Expand an admin edit with its derived columns."""
    data = dict(changes)
    if "name" in data:
        if not data["name"]:
            raise HTTPException(422, "Name cannot be empty")
        data["normalized_name"] = normalize_name(data["name"])
    if "website" in data:
        website = canonical_url(data["website"]) if data["website"] else None
        if data["website"] and not website:
            raise HTTPException(422, "Website must be a valid http(s) URL or domain")
        data.update({
            "website": website,
            "domain": domain_from_url(website),
            "website_status": "verified" if website else None,
            "website_discovery_source": "manual" if website else None,
            "website_verified_at": now() if website else None,
        })
    if "founded_year" in data or "founded_on" in data:
        if data.get("founded_on") and not data.get("founded_year"):
            data["founded_year"] = int(str(data["founded_on"])[:4])
        has_value = bool(data.get("founded_year"))
        data["founded_source"] = "manual" if has_value else None
        if not has_value:
            data["founded_on"] = None
    for key, canonical, example in (
        ("linkedin_url", linkedin_url, "https://www.linkedin.com/company/acme"),
        ("twitter_url", twitter_url, "https://x.com/acme or @acme"),
        ("github_url", github_url, "https://github.com/acme"),
    ):
        if data.get(key):
            value = canonical(data[key])
            if not value:
                raise HTTPException(422, f"{key.replace('_url', '').title()} link must look like {example}")
            data[key] = value
    if data.get("contact_email"):
        email = data["contact_email"].strip().lower().removeprefix("mailto:")
        if not EMAIL_RE.fullmatch(email):
            raise HTTPException(422, "Contact email must be a valid email address")
        data["contact_email"] = email
    if {"has_careers_page", "careers_url", "open_jobs_count"} & data.keys():
        if data.get("careers_url"):
            careers_url = canonical_url(data["careers_url"])
            if not careers_url:
                raise HTTPException(422, "Careers URL must be a valid http(s) URL")
            data["careers_url"] = careers_url
            data.setdefault("has_careers_page", True)
        data["careers_provider"] = "manual" if data.get("has_careers_page") else None
        data["careers_checked_at"] = now()
    return data


def edited_field_names(changes: dict[str, Any]) -> set[str]:
    names = {key for key in changes if key in CompanyFields.model_fields}
    for key in list(names):
        names.update(DERIVED_FIELDS.get(key, []))
    return names


# --- companies ---------------------------------------------------------------
@router.post("/companies", status_code=201)
async def create_company(payload: CompanyCreate, admin: UserContext = Depends(admin_user), settings: Settings = Depends(get_settings)):
    api = SupabaseAPI(settings)
    provided = payload.model_dump(mode="json", exclude_none=True)
    data = curated_changes(provided)
    manual_id = str(uuid.uuid4())
    data.update({
        "source_key": f"manual:{manual_id}",
        "source_name": "Manual entry",
        "source_id": manual_id,
        "source_url": data.get("website") or "",
        "entity_kind": data.get("entity_kind") or "startup",
        "edited_fields": sorted(edited_field_names(provided)),
        "metadata": {"created_by": admin.email},
    })
    if not data.get("location"):
        data["location"] = ", ".join(part for part in (data.get("city"), data.get("state") or data.get("country")) if part) or None
    rows = await api.insert("startup_companies", data)
    invalidate_facets()
    return await company_detail(api, rows[0]["id"], admin.id)


@router.patch("/companies/{company_id}")
async def update_company(
    company_id: str, payload: CompanyUpdate, admin: UserContext = Depends(admin_user), settings: Settings = Depends(get_settings)
):
    api = SupabaseAPI(settings)
    company_id = valid_id(company_id)
    changes = payload.model_dump(mode="json", exclude_unset=True)
    current, _ = await api.select("startup_companies", f"select=id,edited_fields&id={eq(company_id)}&limit=1")
    if not current:
        raise HTTPException(404, "Company not found")
    if changes:
        data = curated_changes(changes)
        data["edited_fields"] = sorted(set(current[0].get("edited_fields") or []) | edited_field_names(changes))
        await api.update("startup_companies", f"id={eq(company_id)}", data)
        invalidate_facets()
    return await company_detail(api, company_id, admin.id)


@router.post("/companies/{company_id}/unlock")
async def unlock_company(company_id: str, admin: UserContext = Depends(admin_user), settings: Settings = Depends(get_settings)):
    """Let sources and enrichment update fields that were edited by hand again."""
    api = SupabaseAPI(settings)
    company_id = valid_id(company_id)
    rows = await api.update("startup_companies", f"id={eq(company_id)}", {"edited_fields": []})
    if not rows:
        raise HTTPException(404, "Company not found")
    return await company_detail(api, company_id, admin.id)


async def delete_companies(api: SupabaseAPI, ids: list[str], admin: UserContext) -> int:
    """Delete companies and remember their source keys so a re-scrape does not re-add them."""
    rows, _ = await api.select("startup_companies", f"select=source_key,name,source_name&id={in_filter(ids)}")
    tombstones = [
        {"source_key": row["source_key"], "name": row["name"], "source_name": row["source_name"], "deleted_by": admin.email}
        for row in rows
        if not row["source_key"].startswith("manual:")
    ]
    if tombstones:
        await api.insert("company_tombstones", tombstones, upsert="source_key")
    deleted = await api.delete("startup_companies", f"id={in_filter(ids)}")
    invalidate_facets()
    return len(deleted)


@router.delete("/companies/{company_id}", status_code=204)
async def delete_company(company_id: str, admin: UserContext = Depends(admin_user), settings: Settings = Depends(get_settings)):
    if not await delete_companies(SupabaseAPI(settings), [valid_id(company_id)], admin):
        raise HTTPException(404, "Company not found")
    return Response(status_code=204)


@router.post("/companies/bulk-delete")
async def bulk_delete(payload: BulkDeleteInput, admin: UserContext = Depends(admin_user), settings: Settings = Depends(get_settings)):
    ids = list(dict.fromkeys(valid_id(item) for item in payload.ids))
    return {"deleted": await delete_companies(SupabaseAPI(settings), ids, admin)}


@router.get("/deleted-companies")
async def deleted_companies(admin: UserContext = Depends(admin_user), settings: Settings = Depends(get_settings)):
    rows, _ = await SupabaseAPI(settings).select(
        "company_tombstones", "select=source_key,name,source_name,deleted_by,deleted_at&order=deleted_at.desc&limit=500"
    )
    return rows


@router.post("/deleted-companies/restore")
async def restore_deleted(payload: dict[str, str], admin: UserContext = Depends(admin_user), settings: Settings = Depends(get_settings)):
    """Allow a deleted company to be re-imported by the next scrape."""
    source_key = (payload.get("source_key") or "").strip()
    if not source_key:
        raise HTTPException(422, "source_key is required")
    await SupabaseAPI(settings).delete("company_tombstones", f"source_key={eq(source_key)}")
    return {"restored": source_key}


@router.post("/companies/{company_id}/enrich")
async def enrich_company(company_id: str, admin: UserContext = Depends(admin_user), settings: Settings = Depends(get_settings)):
    """Re-run website / careers / founding-date discovery for one company now (up to ~90s)."""
    company_id = valid_id(company_id)
    store = SupabaseStore(settings.supabase_url, settings.supabase_service_role_key, origin="enricher")
    rows = await asyncio.to_thread(store.enrichment_rows, [company_id])
    if not rows:
        raise HTTPException(404, "Company not found")
    enricher = Enricher(settings.enrich_user_agent, budget_seconds=75, brave_api_key=settings.brave_search_api_key or "")
    result = await asyncio.to_thread(enricher.enrich, rows[0])
    await asyncio.to_thread(store.save_enrichment, company_id, result.patch)
    invalidate_facets()
    company = await company_detail(SupabaseAPI(settings), company_id, admin.id)
    return {"company": company, "log": result.log, "error": result.error}


# --- funding rounds ------------------------------------------------------------
def round_payload(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("currency"):
        data["currency"] = data["currency"].upper()
    if data.get("amount") is not None and data.get("amount_usd") is None and (data.get("currency") or "USD") == "USD":
        data["amount_usd"] = data["amount"]
    if data.get("valuation_currency"):
        data["valuation_currency"] = data["valuation_currency"].upper()
    if data.get("valuation_usd") is not None and data.get("valuation") is None and "valuation" not in data:
        data.update({"valuation": data["valuation_usd"], "valuation_currency": "USD"})
    elif data.get("valuation") is not None and data.get("valuation_usd") is None and (data.get("valuation_currency") or "USD") == "USD":
        data["valuation_usd"] = data["valuation"]
    if "investors" in data and data["investors"] is not None:
        data["investors"] = [item.strip() for item in data["investors"] if item and item.strip()][:50]
    return data


@router.post("/funding-rounds", status_code=201)
async def create_round(payload: FundingRoundCreate, admin: UserContext = Depends(admin_user), settings: Settings = Depends(get_settings)):
    data = round_payload(payload.model_dump(mode="json", exclude_none=True))
    data["company_id"] = valid_id(data["company_id"])
    data.setdefault("currency", "USD")
    data.setdefault("investors", [])
    round_id = str(uuid.uuid4())
    data.update({
        "source_key": f"manual-round:{round_id}",
        "source_name": "Manual entry",
        "source_url": data.get("source_url") or "",
        "metadata": {"created_by": admin.email},
    })
    rows = await SupabaseAPI(settings).insert("funding_rounds", data)
    invalidate_facets()
    return rows[0]


@router.patch("/funding-rounds/{round_id}")
async def update_round(
    round_id: str, payload: FundingRoundUpdate, admin: UserContext = Depends(admin_user), settings: Settings = Depends(get_settings)
):
    data = round_payload(payload.model_dump(mode="json", exclude_unset=True))
    if "source_url" in data and data["source_url"] is None:
        data["source_url"] = ""
    api = SupabaseAPI(settings)
    if not data:
        rows, _ = await api.select("funding_rounds", f"select=*&id={eq(valid_id(round_id))}")
    else:
        rows = await api.update("funding_rounds", f"id={eq(valid_id(round_id))}", data)
    if not rows:
        raise HTTPException(404, "Funding round not found")
    invalidate_facets()
    return rows[0]


@router.delete("/funding-rounds/{round_id}", status_code=204)
async def delete_round(round_id: str, admin: UserContext = Depends(admin_user), settings: Settings = Depends(get_settings)):
    rows = await SupabaseAPI(settings).delete("funding_rounds", f"id={eq(valid_id(round_id))}")
    if not rows:
        raise HTTPException(404, "Funding round not found")
    invalidate_facets()
    return Response(status_code=204)


# --- coverage & users ------------------------------------------------------------
@router.get("/stats")
async def stats(admin: UserContext = Depends(admin_user), settings: Settings = Depends(get_settings)):
    """Data coverage: how many companies have a website, careers check, founding date, ..."""
    return await SupabaseAPI(settings).rpc("company_coverage", {})


@router.get("/users")
async def users(admin: UserContext = Depends(admin_user), settings: Settings = Depends(get_settings)):
    rows, _ = await SupabaseAPI(settings).select(
        "profiles", "select=id,email,role,created_at,updated_at&order=created_at.asc&limit=1000"
    )
    return rows


@router.patch("/users/{user_id}/role")
async def set_role(user_id: str, payload: RoleInput, admin: UserContext = Depends(admin_user), settings: Settings = Depends(get_settings)):
    user_id = valid_id(user_id)
    if user_id == admin.id and payload.role != "admin":
        raise HTTPException(400, "You cannot remove your own administrator role")
    rows = await SupabaseAPI(settings).update("profiles", f"id={eq(user_id)}", {"role": payload.role})
    if not rows:
        raise HTTPException(404, "User not found")
    forget_user(user_id)
    return rows[0]
