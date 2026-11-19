from __future__ import annotations

import re
from collections.abc import Iterable

from .models import Company, FundingRound


EARLY_STAGE_TYPES = ("pre-seed", "bootstrapped", "pre-funding", "ideation", "self-funded")

_ALIASES: dict[str, tuple[str, ...]] = {
    "pre-seed": (
        r"\bpre[\s-]?seed\b",
        r"\bpreseed\b",
        r"\bfriends?\s+(?:and|&)\s+family\b",
        r"\bangel\s+(?:round|funding|investment)\b",
    ),
    "bootstrapped": (r"\bbootstrap(?:ped|ping)?\b", r"\bboot[\s-]?strapped\b"),
    "pre-funding": (
        r"\bpre[\s-]?fund(?:ing|ed)?\b",
        r"\bunfunded\b",
        r"\bno\s+outside\s+(?:capital|funding|investment)\b",
    ),
    "ideation": (r"\bideation\b", r"\bidea[\s-]?stage\b", r"\bconcept[\s-]?stage\b"),
    "self-funded": (r"\bself[\s-]?fund(?:ed|ing)?\b", r"\bfounder[\s-]?funded\b"),
}


def normalize_requested(values: Iterable[str] | None) -> set[str]:
    selected = {value.strip().lower().replace("_", "-") for value in (values or []) if value.strip()}
    invalid = selected - set(EARLY_STAGE_TYPES)
    if invalid:
        raise ValueError(f"Unknown funding/stage types: {', '.join(sorted(invalid))}")
    return selected


def _searchable(company: Company, funding: FundingRound | None) -> str:
    company_metadata = " ".join(str(value) for value in company.metadata.values() if value)
    funding_metadata = " ".join(str(value) for value in funding.metadata.values() if value) if funding else ""
    return " ".join(
        str(value)
        for value in (
            company.stage, company.status, company.description, company.subindustry, company_metadata,
            funding.round_type if funding else None, funding.title if funding else None,
            funding.summary if funding else None, funding_metadata,
        )
        if value
    ).lower()


def detected_types(company: Company, funding: FundingRound | None = None) -> set[str]:
    text = _searchable(company, funding)
    return {
        stage_type
        for stage_type, patterns in _ALIASES.items()
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)
    }


def filter_by_stage_types(
    companies: list[Company],
    rounds: list[FundingRound],
    requested: Iterable[str] | None,
) -> tuple[list[Company], list[FundingRound]]:
    """Keep only records with explicit evidence for the requested early-stage labels."""
    selected = normalize_requested(requested)
    if not selected:
        return companies, rounds

    company_by_key = {company.source_key: company for company in companies}
    matched_keys: set[str] = set()
    for funding in rounds:
        company = company_by_key.get(funding.company_source_key)
        if company and detected_types(company, funding) & selected:
            matched_keys.add(company.source_key)
    for company in companies:
        if detected_types(company) & selected:
            matched_keys.add(company.source_key)

    return (
        [company for company in companies if company.source_key in matched_keys],
        [funding for funding in rounds if funding.company_source_key in matched_keys],
    )
