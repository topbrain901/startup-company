"""Founding-date extraction. Every value carries its provenance so better evidence can
replace weaker estimates later (ranks are mirrored by public.founded_source_rank in SQL)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date

from .http import WebClient
from .page import PageInfo
from .util import registrable_domain


FOUNDED_SOURCE_RANK = {
    "manual": 100,
    "sec_form_d": 80,
    "yc_profile": 70,
    "wikidata": 60,
    "website_structured_data": 50,
    "website_text": 40,
    "yc_batch_estimate": 25,
    "domain_registration": 20,
    "website_copyright": 15,
}
ESTIMATED_SOURCES = {"yc_batch_estimate", "domain_registration", "website_copyright"}


def founded_rank(source: str | None) -> int:
    if not source:
        return 0
    return FOUNDED_SOURCE_RANK.get(source, 30)


@dataclass(slots=True)
class FoundedFact:
    year: int
    source: str
    on: str | None = None  # ISO date when the full date is known

    @property
    def rank(self) -> int:
        return founded_rank(self.source)


YEAR = r"((?:18|19|20)\d{2})"
MONTHS = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
FOUNDED_TEXT_PATTERNS = (
    re.compile(rf"\b(?:founded|established|incorporated|co-?founded)\s+(?:in\s+|on\s+)?(?:{MONTHS}\s+(?:\d{{1,2}},?\s+)?)?{YEAR}\b", re.I),
    re.compile(rf"\b(?:founded|started|created)\s+(?:back\s+)?in\s+(?:{MONTHS}\s+)?{YEAR}\b", re.I),
    re.compile(rf"\bin\s+(?:{MONTHS}\s+)?{YEAR},?\s+(?:we|our\s+founders?|the\s+company)\s+(?:was\s+)?(?:founded|started|established)\b", re.I),
    re.compile(rf"\best\.?\s*{YEAR}\b", re.I),
    re.compile(rf"\bsince\s+{YEAR}\b", re.I),
)
COPYRIGHT_RANGE_RE = re.compile(rf"(?:©|\(c\)|copyright)\s*{YEAR}\s*[-–—]\s*(?:{YEAR}|present|now)", re.I)
ABOUT_LINK_RE = re.compile(r"/(about(?:-us)?|our-story|story|company|who-we-are|team)(?:[/?#.]|$)", re.I)


def _valid_year(value: str | int) -> int | None:
    year = int(value)
    return year if 1800 <= year <= date.today().year else None


def from_structured_data(page: PageInfo) -> FoundedFact | None:
    def walk(node: object):
        if isinstance(node, dict):
            for key, value in node.items():
                if key.lower() == "foundingdate" and value:
                    yield str(value)
                else:
                    yield from walk(value)
        elif isinstance(node, list):
            for item in node:
                yield from walk(item)

    for raw in page.json_ld:
        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        for value in walk(data):
            match = re.match(r"\s*((?:18|19|20)\d{2})(?:-(\d{2})-(\d{2}))?", value)
            if match and _valid_year(match.group(1)):
                year = int(match.group(1))
                on = f"{year:04d}-{match.group(2)}-{match.group(3)}" if match.group(2) else None
                return FoundedFact(year=year, source="website_structured_data", on=on)
    return None


def from_text(page: PageInfo) -> FoundedFact | None:
    text = page.text[:60_000]
    for pattern in FOUNDED_TEXT_PATTERNS:
        for match in pattern.finditer(text):
            year = _valid_year(match.group(1))
            if year:
                return FoundedFact(year=year, source="website_text")
    match = COPYRIGHT_RANGE_RE.search(text)
    if match and _valid_year(match.group(1)):
        return FoundedFact(year=int(match.group(1)), source="website_copyright")
    return None


def about_page_url(page: PageInfo) -> str | None:
    site = registrable_domain(page.base_url)
    for url, text in page.links:
        if registrable_domain(url) != site:
            continue
        if ABOUT_LINK_RE.search(url) or re.fullmatch(r"\s*(about(?: us)?|our story|company)\s*", text or "", re.I):
            return url.split("#")[0]
    return None


def domain_registration(client: WebClient, url: str) -> str | None:
    """Registration date of the website's domain via RDAP (keyless WHOIS successor)."""
    domain = registrable_domain(url)
    if not domain:
        return None
    data = client.fetch_json(f"https://rdap.org/domain/{domain}", max_bytes=500_000)
    if not isinstance(data, dict):
        return None
    for event in data.get("events") or []:
        if event.get("eventAction") == "registration" and event.get("eventDate"):
            match = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(event["eventDate"]))
            if match and _valid_year(match.group(1)):
                return "-".join(match.groups())
    return None


def best(*facts: FoundedFact | None) -> FoundedFact | None:
    candidates = [fact for fact in facts if fact is not None]
    return max(candidates, key=lambda fact: fact.rank) if candidates else None
