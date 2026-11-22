"""FundingWatcher (fundingwatcher.com): recently funded startups from its free list pages.

Its terms allow crawling within robots.txt but forbid bulk re-publication of the startup and investor
files, which are sold as CSVs. So the collector reads only the handful of pages a visitor lands on
(the "recently funded" list and one page per round stage), never walks the ~1,000 filter
combinations to rebuild the paid file, and skips the founder-contact tables (personal data).
Keep the dashboard private: the terms do not allow publishing this data.
"""

from __future__ import annotations

import html as html_lib
import re
from collections.abc import Callable, Iterable

from ..http import HostThrottle, WebClient
from ..models import Company, FundingRound
from ..util import canonical_url, clean_text, domain_from_url, normalize_name, parse_date, split_location, stable_key


Log = Callable[[str], None]
SOURCE_NAME = "FundingWatcher"
BASE = "https://fundingwatcher.com"
PAGES = (
    f"{BASE}/startups/recently-funded/",
    *(f"{BASE}/rounds/{stage}/" for stage in ("pre-seed", "seed", "series-a", "series-b", "series-c", "series-d-plus")),
)
REQUIRED_COLUMNS = {"company", "what they do", "last round", "date"}
PERSONAL_COLUMNS = {"person", "title", "verified email", "email"}  # founder contacts: never collected

TABLE_RE = re.compile(r"<table\b.*?</table>", re.S | re.I)
ROW_RE = re.compile(r"<tr\b.*?</tr>", re.S | re.I)
CELL_RE = re.compile(r"<t([hd])\b[^>]*>(.*?)</t\1>", re.S | re.I)
LINK_RE = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
MONEY_RE = re.compile(r"^\$\s*(\d+(?:\.\d+)?)\s*([KMB])?$", re.I)
EMPLOYEES_RE = re.compile(r"^([\d,]+)\s*(?:to|-|–)\s*([\d,]+)$|^([\d,]+)\+$")


def web_client(user_agent: str) -> WebClient:
    return WebClient(
        user_agent=user_agent,
        timeout=25,
        max_bytes=4_000_000,
        throttle=HostThrottle(default_interval=2.0, intervals={"fundingwatcher.com": 2.0}),
    )


def _text(fragment: str) -> str:
    return clean_text(html_lib.unescape(re.sub(r"<[^>]+>", " ", fragment)))


def money(value: str) -> float | None:
    """'$107K' -> 107000, '$5.1M' -> 5100000, '$3.5B' -> 3.5e9."""
    match = MONEY_RE.match(value.strip())
    if not match:
        return None
    unit = (match.group(2) or "").upper()
    return float(match.group(1)) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[unit]


def employees(value: str) -> tuple[int | None, str | None]:
    """'11 to 50' -> (11, '11–50'); '5,001+' -> (5001, '5,001+'). The lower bound is stored as the count."""
    value = value.strip()
    match = EMPLOYEES_RE.match(value)
    if not match:
        return None, None
    if match.group(3):
        return int(match.group(3).replace(",", "")), value
    return int(match.group(1).replace(",", "")), f"{match.group(1)}–{match.group(2)}"


def investors(value: str) -> tuple[list[str], int]:
    """'A, B, C +2' -> (['A', 'B', 'C'], 2): the page lists the first few only."""
    more = 0
    match = re.search(r"\s*\+(\d+)\s*$", value)
    if match:
        more, value = int(match.group(1)), value[: match.start()]
    names = [name.strip() for name in value.split(",") if name.strip() and name.strip() not in {"—", "-"}]
    return names, more


def parse_page(page_html: str, page_url: str) -> Iterable[dict]:
    """Rows of every company table on a list page, keyed by lower-cased column header."""
    for table in TABLE_RE.findall(page_html):
        rows = ROW_RE.findall(table)
        if not rows:
            continue
        header = [_text(cell).lower() for _, cell in CELL_RE.findall(rows[0])]
        if not REQUIRED_COLUMNS <= set(header) or PERSONAL_COLUMNS & set(header):
            continue
        for row in rows[1:]:
            cells = [cell for _, cell in CELL_RE.findall(row)]
            if len(cells) != len(header):
                continue
            record = {key: _text(cell) for key, cell in zip(header, cells)}
            company_cell = cells[header.index("company")]
            link = LINK_RE.search(company_cell)
            # The anchor holds the name; badges such as "Unicorn" sit outside it.
            record["company"] = _text(link.group(2)) if link else record["company"]
            record["website"] = canonical_url(html_lib.unescape(link.group(1))) if link else None
            record["page_url"] = page_url
            yield record


def to_models(record: dict) -> tuple[Company, FundingRound] | None:
    name = record.get("company", "").strip()
    if not name or len(name) > 160:
        return None
    website = record.get("website")
    domain = domain_from_url(website)
    identity = domain or normalize_name(name)
    source_key = stable_key("fundingwatcher", identity)
    place = split_location(record.get("location"))
    team, team_range = employees(record.get("employees", ""))
    names, more = investors(record.get("investors", ""))
    amount = money(record.get("amount", ""))
    total = money(record.get("total raised", ""))
    founded = record.get("founded", "")
    round_type = record.get("last round") or None
    announced = parse_date(record.get("date"))
    company = Company(
        source_key=source_key,
        source_name=SOURCE_NAME,
        source_id=identity,
        source_url=record["page_url"],
        name=name,
        normalized_name=normalize_name(name),
        website=website,
        domain=domain,
        description=record.get("what they do") or None,
        city=place["city"],
        state=place["state"],
        country=place["country"],
        location=record.get("location") or None,
        industry=record.get("sector") or None,
        entity_kind="startup",
        founded_year=int(founded) if founded.isdigit() and 1800 < int(founded) < 2100 else None,
        founded_source="fundingwatcher" if founded.isdigit() else None,
        employee_count=team,
        metadata={
            key: value
            for key, value in {
                "employees_range": team_range,
                "total_raised_usd": total,
                "listing_url": record["page_url"],
            }.items()
            if value is not None
        },
    )
    funding = FundingRound(
        source_key=stable_key("fundingwatcher-round", f"{identity}|{announced}|{round_type}"),
        company_source_key=source_key,
        source_name=SOURCE_NAME,
        source_url=record["page_url"],
        announced_on=announced,
        round_type=round_type,
        amount=amount,
        currency="USD" if amount is not None else None,
        amount_usd=amount,
        investors=names,
        title=" ".join(part for part in (name, "raised", record.get("amount"), round_type) if part),
        metadata={key: value for key, value in {"more_investors": more or None, "total_raised_usd": total}.items() if value},
    )
    return company, funding


def collect(*, user_agent: str, limit: int | None = None, log: Log = print) -> Iterable[tuple[Company, FundingRound]]:
    client = web_client(user_agent)
    seen: set[str] = set()
    emitted = 0
    for url in PAGES:
        result = client.fetch(url)
        if not result.ok:
            log(f"warning: skipped {url}: {result.error or f'HTTP {result.status}'}")
            continue
        for record in parse_page(result.text(), url):
            models = to_models(record)
            if models is None or models[0].source_key in seen:
                continue
            seen.add(models[0].source_key)
            yield models
            emitted += 1
            if limit is not None and emitted >= limit:
                return
