"""Public early-stage directories that do not require paid API credentials.

Every HTML request goes through WebClient, which identifies the bot, honours robots.txt,
caps response sizes, and rate-limits hosts. Parsers intentionally use only public list pages.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from datetime import date
from urllib.parse import urljoin

from ..http import HostThrottle, WebClient
from ..models import Company
from ..util import canonical_url, clean_text, domain_from_url, normalize_name, split_location, stable_key


Log = Callable[[str], None]
SUPPORTED = ("producthunt", "betalist", "antler", "ef", "techstars", "wellfound")

DIRECTORY_URLS = {
    "producthunt": "https://www.producthunt.com/feed",
    "betalist": "https://betalist.com/startups",
    "antler": "https://www.antler.co/portfolio",
    "ef": "https://www.joinef.com/portfolio/",
    "techstars": "https://www.techstars.com/portfolio",
    "wellfound": "https://wellfound.com/discover/startups",
}


def web_client(user_agent: str) -> WebClient:
    return WebClient(
        user_agent=user_agent,
        timeout=25,
        max_bytes=6_000_000,
        throttle=HostThrottle(
            default_interval=0.8,
            intervals={
                "www.joinef.com": 10.0,
                "portfolio.joinef.com": 10.0,
                "www.antler.co": 10.0,
                "betalist.com": 1.0,
                "wellfound.com": 1.0,
                "www.producthunt.com": 1.0,
                "www.techstars.com": 1.0,
            },
        ),
    )


def _html(client: WebClient, url: str, log: Log) -> str:
    result = client.fetch(url, max_bytes=6_000_000)
    if not result.ok:
        log(f"warning: skipped {url}: {result.error or f'HTTP {result.status}'}")
        return ""
    return result.text()


def _company(
    *,
    source: str,
    source_name: str,
    external_id: str,
    source_url: str,
    name: str,
    website: str | None = None,
    description: str | None = None,
    location: str | None = None,
    industry: str | None = None,
    founded_year: int | None = None,
    stage: str | None = None,
    status: str | None = None,
    metadata: dict | None = None,
) -> Company | None:
    name = clean_text(name).strip(" -–—|")
    if not (1 < len(name) <= 300):
        return None
    website = canonical_url(website)
    place = split_location(location)
    return Company(
        source_key=stable_key(source, external_id),
        source_name=source_name,
        source_id=external_id,
        source_url=source_url,
        name=name,
        normalized_name=normalize_name(name),
        website=website,
        domain=domain_from_url(website),
        description=clean_text(description)[:4000] or None,
        city=place["city"],
        state=place["state"],
        country=place["country"],
        location=location,
        is_remote=place["is_remote"],
        industry=clean_text(industry) or None,
        entity_kind="startup",
        founded_year=founded_year,
        founded_source=f"{source}_directory" if founded_year else None,
        status=status,
        stage=stage,
        metadata={"directory": source_name, **(metadata or {})},
    )


def product_hunt(client: WebClient, limit: int | None, log: Log) -> Iterable[Company]:
    result = client.fetch(
        DIRECTORY_URLS["producthunt"],
        accept="application/atom+xml,application/xml;q=0.9,*/*;q=0.5",
        max_bytes=3_000_000,
    )
    if not result.ok:
        log(f"warning: skipped Product Hunt: {result.error or f'HTTP {result.status}'}")
        return
    try:
        root = ET.fromstring(result.body)
    except ET.ParseError as exc:
        log(f"warning: skipped Product Hunt: invalid Atom feed ({exc})")
        return
    emitted = 0
    for entry in root.iter():
        if entry.tag.rsplit("}", 1)[-1] != "entry":
            continue
        values: dict[str, str] = {}
        link = ""
        for child in entry:
            key = child.tag.rsplit("}", 1)[-1]
            if key == "link" and child.attrib.get("rel", "alternate") == "alternate":
                link = child.attrib.get("href", "")
            elif child.text:
                values[key] = child.text
        external_id = values.get("id") or link
        company = _company(
            source="product-hunt",
            source_name="Product Hunt",
            external_id=external_id,
            source_url=link or DIRECTORY_URLS["producthunt"],
            name=values.get("title", ""),
            description=values.get("content"),
            stage="Product launch",
            status="Launched",
            metadata={"published": values.get("published"), "updated": values.get("updated")},
        )
        if company:
            yield company
            emitted += 1
            if limit is not None and emitted >= limit:
                return


BETALIST_CARD = re.compile(r'<div class="[^"]*(?<![.\w-])startup-row(?![:\w-])[^"]*">', re.I)


def betalist(client: WebClient, limit: int | None, log: Log) -> Iterable[Company]:
    emitted = 0
    seen: set[str] = set()
    for page in range(1, 21):
        url = DIRECTORY_URLS["betalist"] + ("" if page == 1 else f"?page={page}")
        text = _html(client, url, log)
        if not text:
            return
        page_new = 0
        for _, block in _blocks(text, BETALIST_CARD):
            identity = re.search(r'href="/startups/([^"/?#]+)"', block, re.I)
            values = re.findall(r'<span[^>]*>(.*?)</span>', block, re.I | re.S)
            if not identity or len(values) < 2:
                continue
            slug = identity.group(1)
            if slug in seen:
                continue
            seen.add(slug)
            company = _company(
                source="betalist",
                source_name="BetaList",
                external_id=slug,
                source_url=f"https://betalist.com/startups/{slug}",
                name=values[0],
                description=values[1],
                stage="Ideation",
                status="Pre-launch / early access",
                metadata={"stage_inferred_from_directory": True},
            )
            if company:
                yield company
                page_new += 1
                emitted += 1
                if limit is not None and emitted >= limit:
                    return
        if page_new == 0:
            return


def _blocks(text: str, marker: re.Pattern[str]) -> Iterable[tuple[re.Match[str], str]]:
    matches = list(marker.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        yield match, text[match.start():end]


ANTLER_CARD = re.compile(r'<div class="portco_card">', re.I)


def antler(client: WebClient, limit: int | None, log: Log) -> Iterable[Company]:
    text = _html(client, DIRECTORY_URLS["antler"], log)
    emitted = 0
    for _, block in _blocks(text, ANTLER_CARD):
        name = re.search(r'fs-cmsfilter-field="name"[^>]*>(.*?)</p>', block, re.I | re.S)
        description = re.search(r'fs-cmsfilter-field="description"[^>]*>(.*?)</p>', block, re.I | re.S)
        tags = [clean_text(value) for value in re.findall(r'fs-cmsfilter-field="location"[^>]*>(.*?)</div>', block, re.I | re.S)]
        link = re.search(r'<a[^>]+href="([^"]+)"[^>]*class="clickable_link', block, re.I)
        if not name:
            continue
        location = tags[0] if tags else None
        industry = tags[1] if len(tags) > 1 else None
        raw_year = tags[2] if len(tags) > 2 else ""
        founded_year = int(raw_year) if raw_year.isdigit() and 1800 <= int(raw_year) <= date.today().year else None
        recent = bool(founded_year and founded_year >= date.today().year - 1)
        website = urljoin(DIRECTORY_URLS["antler"], link.group(1)) if link else None
        company = _company(
            source="antler",
            source_name="Antler portfolio",
            external_id=website or f"{clean_text(name.group(1))}:{raw_year}",
            source_url=DIRECTORY_URLS["antler"],
            name=name.group(1),
            website=website,
            description=description.group(1) if description else None,
            location=location,
            industry=industry,
            founded_year=founded_year,
            stage="Pre-Seed" if recent else "Antler portfolio",
            status="Portfolio company",
            metadata={"accelerator": "Antler", "stage_inferred_from_recent_cohort": recent},
        )
        if company:
            yield company
            emitted += 1
            if limit is not None and emitted >= limit:
                return


EF_CARD = re.compile(r'<div class="tile tile--company[^>]*>', re.I)


def entrepreneur_first(client: WebClient, limit: int | None, log: Log) -> Iterable[Company]:
    emitted = 0
    seen: set[str] = set()
    for page in range(1, 13):
        url = DIRECTORY_URLS["ef"] if page == 1 else f"{DIRECTORY_URLS['ef']}?pagenum={page}"
        text = _html(client, url, log)
        if not text:
            return
        page_new = 0
        for _, block in _blocks(text, EF_CARD):
            # Featured companies are mature showcase entries repeated before the paginated,
            # newest-first portfolio. The regular list is the useful early-stage feed.
            if 'data-featured="true"' in block:
                continue
            identity = re.search(r'data-companyname="([^"]+)"[^>]*data-companyslug="([^"]+)"', block, re.I)
            if not identity:
                identity = re.search(r'data-companyslug="([^"]+)"[^>]*data-companyname="([^"]+)"', block, re.I)
                if identity:
                    slug, name = identity.group(1), identity.group(2)
                else:
                    continue
            else:
                name, slug = identity.group(1), identity.group(2)
            if slug in seen:
                continue
            seen.add(slug)
            description = re.search(r'tile__description[^>]*>(.*?)</div>', block, re.I | re.S)
            locations = re.findall(r"class=['\"]locationtag['\"][^>]*>(.*?)</a>", block, re.I | re.S)
            industries = re.findall(r"class=['\"]categorytag['\"][^>]*>(.*?)</a>", block, re.I | re.S)
            year_match = re.search(
                r'meta__row__name[^>]*>\s*Founded\s*</div>.*?meta__row__name[^>]*>\s*(20\d{2}|19\d{2})',
                block,
                re.I | re.S,
            )
            founded_year = int(year_match.group(1)) if year_match else None
            recent = bool(founded_year and founded_year >= date.today().year - 1)
            company = _company(
                source="entrepreneur-first",
                source_name="Entrepreneur First portfolio",
                external_id=slug,
                source_url=f"https://www.joinef.com/companies/{slug}/",
                name=name,
                description=description.group(1) if description else None,
                location=clean_text(locations[0]) if locations else None,
                industry=clean_text(industries[0]) if industries else None,
                founded_year=founded_year,
                stage="Pre-Seed" if recent else "EF portfolio",
                status="Portfolio company",
                metadata={
                    "accelerator": "Entrepreneur First",
                    "industries": [clean_text(item) for item in industries],
                    "stage_inferred_from_recent_cohort": recent,
                },
            )
            if company:
                yield company
                emitted += 1
                page_new += 1
                if limit is not None and emitted >= limit:
                    return
        if page_new == 0:
            return


TECHSTARS_CARD = re.compile(
    r'MuiTypography-h5[^>]*>(?P<name>.*?)</p>\s*'
    r'<p[^>]*MuiTypography-caption[^>]*>(?P<year>.*?)</p>.*?'
    r'MuiTypography-body2[^>]*>(?P<description>.*?)</p>.*?'
    r'<a[^>]*href="(?P<website>[^"]+)"[^>]*aria-label="Website"',
    re.I | re.S,
)


def techstars(client: WebClient, limit: int | None, log: Log) -> Iterable[Company]:
    text = _html(client, DIRECTORY_URLS["techstars"], log)
    emitted = 0
    for match in TECHSTARS_CARD.finditer(text):
        raw_year = clean_text(match.group("year"))
        founded_year = int(raw_year) if raw_year.isdigit() and 1800 <= int(raw_year) <= date.today().year else None
        recent = bool(founded_year and founded_year >= date.today().year - 1)
        company = _company(
            source="techstars",
            source_name="Techstars portfolio",
            external_id=match.group("website"),
            source_url=DIRECTORY_URLS["techstars"],
            name=match.group("name"),
            website=match.group("website"),
            description=match.group("description"),
            founded_year=founded_year,
            stage="Pre-Seed" if recent else "Techstars portfolio",
            status="Portfolio company",
            metadata={"accelerator": "Techstars", "stage_inferred_from_recent_cohort": recent},
        )
        if company:
            yield company
            emitted += 1
            if limit is not None and emitted >= limit:
                return


WELLFOUND_CARD = re.compile(r'<a[^>]+href="/company/(?P<slug>[^"/]+)"[^>]*>', re.I)


def wellfound(client: WebClient, limit: int | None, log: Log) -> Iterable[Company]:
    emitted = 0
    seen: set[str] = set()
    for page in range(1, 21):
        url = DIRECTORY_URLS["wellfound"] + ("" if page == 1 else f"?page={page}")
        text = _html(client, url, log)
        if not text:
            return
        page_new = 0
        for marker, block in _blocks(text, WELLFOUND_CARD):
            slug = marker.group("slug")
            if slug in seen:
                continue
            name = re.search(r'class="[^"]*(?:text-lg|lg:text-xl)[^"]*"[^>]*>(.*?)</div>', block, re.I | re.S)
            if not name:
                continue
            seen.add(slug)
            description = re.search(r'class="[^"]*line-clamp-2[^"]*"[^>]*>(.*?)</div>', block, re.I | re.S)
            industries = re.findall(r'href="/startups/industry/[^"]+"[^>]*>(.*?)</a>', block, re.I | re.S)
            locations = re.findall(r'href="/location/[^"]+"[^>]*>(.*?)</a>', block, re.I | re.S)
            location = ", ".join(dict.fromkeys(clean_text(item) for item in locations if clean_text(item))) or None
            company = _company(
                source="wellfound",
                source_name="Wellfound startup directory",
                external_id=slug,
                source_url=f"https://wellfound.com/company/{slug}",
                name=name.group(1),
                description=description.group(1) if description else None,
                location=location,
                industry=clean_text(industries[0]) if industries else None,
                stage="Wellfound startup",
                status="Listed",
                metadata={"industries": [clean_text(item) for item in industries]},
            )
            if company:
                yield company
                emitted += 1
                page_new += 1
                if limit is not None and emitted >= limit:
                    return
        if page_new == 0:
            return


COLLECTORS = {
    "producthunt": product_hunt,
    "betalist": betalist,
    "antler": antler,
    "ef": entrepreneur_first,
    "techstars": techstars,
    "wellfound": wellfound,
}


def collect(source: str, *, user_agent: str, limit: int | None = None, log: Log = print) -> Iterable[Company]:
    if source not in COLLECTORS:
        raise ValueError(f"Unknown early-stage source: {source}")
    yield from COLLECTORS[source](web_client(user_agent), limit, log)
