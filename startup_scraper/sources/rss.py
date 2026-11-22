from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Iterable

from ..http import HttpClient
from ..models import Company, FundingRound
from ..places import place_from_news
from ..util import clean_text, normalize_name, parse_date, stable_key


@dataclass(frozen=True)
class Feed:
    name: str
    url: str


DEFAULT_FEEDS = (
    Feed("TechCrunch Venture", "https://techcrunch.com/category/venture/feed/"),
    Feed("Crunchbase News", "https://news.crunchbase.com/feed/"),
    Feed("EU-Startups Funding", "https://www.eu-startups.com/category/funding/feed/"),
    Feed("Tech.eu", "https://tech.eu/feed/"),
    Feed("VentureBeat", "https://venturebeat.com/feed/"),
)

FUNDING_WORDS = re.compile(
    r"\b(rais(?:e|es|ed|ing)|secur(?:e|es|ed|ing)|funding|financing|investment|seed|series\s+[a-z]|venture round)\b",
    re.I,
)
COMPANY_RE = re.compile(
    r"^(?P<name>.+?)\s+(?:raises?|raised|secures?|secured|lands?|landed|closes?|closed|bags?|bagged|nabs?|nabbed|gets?|got|receives?|received|picks?\s+up)\b",
    re.I,
)
VALUATION_RAISE_RE = re.compile(
    r"^(?P<name>.+?)\s+(?:hits?|reaches?)\s+.+?\bvaluation\b.+?\braise\b",
    re.I,
)
AMOUNT_RE = re.compile(
    r"(?P<currency>US\$|USD|CA\$|C\$|A\$|AU\$|£|€|\$)\s*(?P<number>\d+(?:[.,]\d+)?)\s*(?P<unit>billion|million|thousand|bn|mm|m|k|b)\b",
    re.I,
)
ROUND_RE = re.compile(r"\b(pre[- ]seed|seed|series\s+[a-z0-9]+|growth|venture|debt|grant)\b", re.I)
FUND_MANAGER_RE = re.compile(
    r"\b(?:debut|new|venture|vc|growth|second|third|fourth)\s+fund\b|"
    r"\bfund\s+(?:to|for)\s+(?:back|invest)|\bbacker\b|\bcloses?\s+(?:its\s+)?fund\b",
    re.I,
)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(node: ET.Element, *names: str) -> str:
    wanted = {name.lower() for name in names}
    for child in node.iter():
        if _local_name(child.tag) in wanted and child.text:
            return child.text.strip()
    return ""


VALUATION_AFTER_RE = re.compile(r"^\s*(?:post-money\s+|pre-money\s+)?valuation\b", re.I)
VALUATION_BEFORE_RE = re.compile(
    r"\b(?:valued\s+(?:it\s+|the\s+(?:company|startup|business)\s+)?at|valuing\s+(?:it|the\s+(?:company|startup|business))\s+at|"
    r"valuation\s+(?:of|to|at))"
    r"(?:\s+(?:about|around|roughly|nearly|almost|over|more\s+than|just\s+over|some|approximately|an\s+estimated))*\s*$",
    re.I,
)


def _money(match: re.Match) -> tuple[float, str]:
    raw = match.group("number").replace(",", ".")
    value = float(raw)
    unit = match.group("unit").lower()
    multiplier = 1_000_000_000 if unit in {"b", "bn", "billion"} else 1_000_000 if unit in {"m", "mm", "million"} else 1_000
    symbol = match.group("currency").upper()
    currency = {"$": "USD", "US$": "USD", "USD": "USD", "£": "GBP", "€": "EUR", "CA$": "CAD", "C$": "CAD", "A$": "AUD", "AU$": "AUD"}.get(symbol, symbol)
    return value * multiplier, currency


def _is_valuation(text: str, match: re.Match) -> bool:
    """'$1B valuation', 'valued at $1B', 'valuation of $1B'."""
    after = text[match.end() : match.end() + 30]
    before = text[max(0, match.start() - 60) : match.start()]
    return bool(VALUATION_AFTER_RE.match(after) or VALUATION_BEFORE_RE.search(before))


def _amount(text: str):
    """Size of the round: the amount nearest a funding word, never the valuation."""
    matches = [match for match in AMOUNT_RE.finditer(text) if not _is_valuation(text, match)]
    if not matches:
        return None, None
    funding_positions = [match.start() for match in re.finditer(r"\b(?:rais\w*|secur\w*|funding|financing|round)\b", text, re.I)]
    match = min(
        matches,
        key=lambda item: min((abs(item.end() - position) for position in funding_positions), default=item.start()),
    )
    return _money(match)


def _valuation(text: str):
    for match in AMOUNT_RE.finditer(text):
        if _is_valuation(text, match):
            return _money(match)
    return None, None


DESCRIPTOR_PREFIX_RE = re.compile(
    r"^.*?\b(?:startup|start-up|scale-?up|upstart|newcomer|spinout|spin-off|unicorn|company|firm|"
    r"platform|maker|developer|provider|specialist|outfit|player)\s+(?=\S)",
    re.I,
)
HYPHEN_DESCRIPTOR_RE = re.compile(r"^(?:\S+\s+)*?\S+-(?:based|backed|founded|focused|led|native)\s+", re.I)
TRAILING_CLAUSE_RE = re.compile(r"\s+(?:with|after|as|amid|backed by|led by|in a|in an)\b.*$", re.I)
NAME_CONNECTORS = {"of", "and", "de", "la", "le", "von", "van", "der", "du", "for", "the", "del", "da"}


def _clean_company_name(name: str) -> str:
    """Strip headline descriptors: 'Finnish healthtech Treat' -> 'Treat'."""
    name = TRAILING_CLAUSE_RE.sub("", name).strip()
    name = HYPHEN_DESCRIPTOR_RE.sub("", name).strip()
    stripped = DESCRIPTOR_PREFIX_RE.sub("", name).strip()
    if stripped and stripped != name and stripped[:1].isupper():
        name = stripped
    tokens = name.split()
    # Lowercase dictionary words ("healthtech", "fintech") are descriptors; brands such as
    # "dbt" or "n8n" are short or contain digits and are kept.
    descriptor_positions = [
        index for index, token in enumerate(tokens)
        if token.isalpha() and token.islower() and len(token) >= 4 and token not in NAME_CONNECTORS
    ]
    if descriptor_positions and descriptor_positions[-1] < len(tokens) - 1:
        tokens = tokens[descriptor_positions[-1] + 1:]
    return " ".join(tokens).strip(" :'\"–—-,")


def _company_name(title: str) -> str | None:
    title = re.sub(r"^[^:]{2,35}:\s+", "", title).strip()
    match = VALUATION_RAISE_RE.search(title) or COMPANY_RE.search(title)
    if not match:
        return None
    name = _clean_company_name(match.group("name").strip(" :'\"–—-"))
    return name if 1 < len(name) <= 160 else None


# Phrases that introduce investor names, up to the end of the sentence.
INVESTOR_LEAD_RE = re.compile(
    r"\b(?:co-?led\s+by|led\s+by|participation\s+(?:from|by)|joined\s+by|backed\s+by|"
    r"investors?\s+(?:include|includes|including|such\s+as|like)|"
    r"(?:existing|returning|new|other)\s+(?:backers?|investors?)(?:\s+(?:including|such\s+as|like))?|"
    # "raised $5M from X", but never across "led by" / "participation" (those leads come first).
    r"(?:rais\w*|secur\w*|clos\w*|land\w*|gets?|got|bags?|bagged)\s+(?:(?!led\s*by|participation)[^.;]){0,60}?\bfrom)"
    # Some feeds drop the space after a line break ("led byWarsaw Equity").
    r"(?:\s+|(?=[A-Z]))(?P<names>.+?)(?=[.;](?:\s|$)|$)",
    re.I,
)
INVESTOR_CLAUSE_END_RE = re.compile(
    r",?\s+(?:which|who|that|bringing|taking|marking|to|for|as|in\s+(?:a|an|the|its|\d{4})|after|amid|"
    r"(?:also\s+)?(?:participated|joined|invested|contributed|took\s+part))\b.*$",
    re.I,
)
# Longer connectors first: at a comma, ", with participation from" must win over ",".
INVESTOR_SPLIT_RE = re.compile(
    r",?\s+with\s+participation\s+(?:from|by)\s+|,?\s+joined\s+by\s+|,?\s+alongside\s+|,?\s+along\s+with\s+|"
    r",?\s+as\s+well\s+as\s+|,?\s+plus\s+|,\s*(?:and\s+)?|\s+and\s+",
    re.I,
)
INVESTOR_PREFIX_RE = re.compile(
    r"^(?:(?:\S+-based|the|its|their|existing|returning|new|other|prior|previous|several|leading|notable|venture|vc|"
    r"investors?|backers?|firms?|funds?|including|include|such\s+as|like|the\s+likes\s+of|participation\s+from)\s+)+",
    re.I,
)
GENERIC_INVESTORS = {
    "others", "other investors", "angel investors", "angels", "existing investors", "strategic investors",
    "undisclosed investors", "a group of investors", "family offices", "individual investors", "investors",
    "a number of angel investors", "several angel investors", "high-profile angels", "industry angels",
}


def _investors(text: str) -> list[str]:
    investors: list[str] = []
    for match in INVESTOR_LEAD_RE.finditer(text):
        value = INVESTOR_CLAUSE_END_RE.sub("", clean_text(match.group("names")))
        for name in INVESTOR_SPLIT_RE.split(value):
            name = re.sub(r"\s+(?:and|among)\s+others$", "", name.strip(" :'\""), flags=re.I)
            name = INVESTOR_PREFIX_RE.sub("", name).strip(" :'\"")
            # Drop only unbalanced brackets: keep "Warsaw Equity Group (WEG)".
            while name.startswith("(") and name.count("(") > name.count(")"):
                name = name[1:].strip()
            while name.endswith(")") and name.count(")") > name.count("("):
                name = name[:-1].strip()
            if (
                not name
                or name.endswith(("..", "…"))  # cut off by a truncated feed summary
                or name.lower() in GENERIC_INVESTORS
                or not (name[0].isupper() or name[0].isdigit() or re.search(r"\d", name.split()[0]))
                or not 1 < len(name) <= 80
                or len(name.split()) > 8
                or AMOUNT_RE.search(name)
            ):
                continue
            if name.lower() not in {item.lower() for item in investors}:
                investors.append(name)
    return investors[:25]


def collect(client: HttpClient, limit: int | None = None, feeds: tuple[Feed, ...] = DEFAULT_FEEDS) -> Iterable[tuple[Company, FundingRound]]:
    emitted = 0
    def fetch(feed: Feed):
        try:
            return feed, client.request(feed.url, retries=0), None
        except Exception as exc:
            return feed, None, exc

    # Feeds are independent; fetching concurrently bounds latency to the slowest feed.
    with ThreadPoolExecutor(max_workers=min(5, len(feeds))) as pool:
        fetched = list(pool.map(fetch, feeds))
    for feed, payload, error in fetched:
        if error is not None:
            exc = error
            print(f"warning: skipped feed {feed.name}: {exc}")
            continue
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            print(f"warning: skipped feed {feed.name}: invalid XML ({exc})")
            continue
        entries = [node for node in root.iter() if _local_name(node.tag) in {"item", "entry"}]
        for entry in entries:
            title = clean_text(_child_text(entry, "title"))
            summary = clean_text(_child_text(entry, "description", "summary", "content"))
            combined = f"{title} {summary}"
            if not FUNDING_WORDS.search(combined):
                continue
            # Fund managers raising an investment fund are not startup recipients.
            if FUND_MANAGER_RE.search(title):
                continue
            name = _company_name(title)
            if not name:
                continue
            link = _child_text(entry, "link", "guid", "id")
            if not link:
                for child in entry.iter():
                    if _local_name(child.tag) == "link" and child.attrib.get("href"):
                        link = child.attrib["href"]
                        break
            if not link:
                continue
            source_key = stable_key("news", link)
            amount, currency = _amount(combined)
            valuation, valuation_currency = _valuation(combined)
            round_match = ROUND_RE.search(combined)
            place = place_from_news(title, summary, name) or {}
            company = Company(
                source_key=source_key,
                source_name=feed.name,
                source_id=link,
                source_url=link,
                name=name,
                normalized_name=normalize_name(name),
                description=summary[:4000] or None,
                city=place.get("city"),
                state=place.get("state"),
                country=place.get("country"),
                location=place.get("location") or None,
                entity_kind="startup",
                metadata={"article_title": title, "feed_url": feed.url, "article_url": link},
            )
            funding = FundingRound(
                source_key=stable_key("round", link),
                company_source_key=source_key,
                source_name=feed.name,
                source_url=link,
                announced_on=parse_date(_child_text(entry, "pubdate", "published", "updated", "date")),
                round_type=round_match.group(0).title() if round_match else None,
                amount=amount,
                currency=currency,
                amount_usd=amount if currency == "USD" else None,
                valuation=valuation,
                valuation_currency=valuation_currency,
                valuation_usd=valuation if valuation_currency == "USD" else None,
                investors=_investors(f"{title}. {summary}"),
                title=title,
                summary=summary[:4000] or None,
                metadata={"feed_url": feed.url, "amount_requires_verification": amount is not None},
            )
            yield company, funding
            emitted += 1
            if limit is not None and emitted >= limit:
                return

