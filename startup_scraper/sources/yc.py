from __future__ import annotations

from typing import Iterable

from ..http import HttpClient
from ..models import Company
from ..util import batch_year, canonical_url, domain_from_url, normalize_name, split_location, stable_key


YC_API = "https://yc-oss.github.io/api/companies/all.json"


def collect(client: HttpClient, limit: int | None = None) -> Iterable[Company]:
    rows = client.json(YC_API)
    for index, item in enumerate(rows):
        if limit is not None and index >= limit:
            break
        source_id = str(item["id"])
        website = canonical_url(item.get("website"))
        location = item.get("all_locations") or None
        place = split_location(location)
        batch = item.get("batch")
        # yc-oss "launched_at" is when the YC profile was published (2012 for Stripe), not the
        # founding date. The batch year is a closer estimate until enrichment reads the profile.
        estimate = batch_year(batch)
        yield Company(
            source_key=stable_key("yc", source_id),
            source_name="Y Combinator directory",
            source_id=source_id,
            source_url=item.get("url") or f"https://www.ycombinator.com/companies/{item.get('slug', '')}",
            name=item["name"].strip(),
            normalized_name=normalize_name(item["name"]),
            website=website,
            domain=domain_from_url(website),
            description=item.get("long_description") or item.get("one_liner"),
            city=place["city"],
            state=place["state"],
            country=place["country"],
            location=location,
            is_remote=place["is_remote"],
            industry=item.get("industry"),
            subindustry=item.get("subindustry"),
            entity_kind="startup",
            founded_year=estimate,
            founded_source="yc_batch_estimate" if estimate else None,
            employee_count=item.get("team_size"),
            status=item.get("status"),
            accelerator_batch=batch,
            stage=item.get("stage"),
            is_hiring=item.get("isHiring"),
            logo_url=item.get("small_logo_thumb_url"),
            metadata={
                "one_liner": item.get("one_liner"),
                "former_names": item.get("former_names") or [],
                "tags": item.get("tags") or [],
                "regions": item.get("regions") or [],
                "top_company": bool(item.get("top_company")),
                "nonprofit": bool(item.get("nonprofit")),
                "yc_slug": item.get("slug"),
                "yc_profile_launched_at": item.get("launched_at"),
                "mirror_api": item.get("api"),
            },
        )
