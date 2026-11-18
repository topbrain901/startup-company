from __future__ import annotations

import hashlib
import html
import re
import threading
import time
import unicodedata
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse


TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = TAG_RE.sub(" ", html.unescape(value))
    return SPACE_RE.sub(" ", value).strip()


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", " ", value).strip().lower()
    return SPACE_RE.sub(" ", value)


# Legal-form words that never belong in a brand or domain name.
LEGAL_WORDS = {
    "inc", "incorporated", "llc", "l", "c", "ltd", "limited", "corp", "corporation", "co", "company",
    "plc", "gmbh", "sa", "sas", "sarl", "bv", "ag", "ab", "oy", "as", "lp", "llp", "pbc", "pllc", "pc",
    "pte", "pty", "srl", "spa", "nv", "kg", "ug", "the",
}


def core_name(value: str) -> str:
    """Brand-like company name: normalized, without legal suffixes or 'dba' tails."""
    value = re.split(r"\b(?:d/?b/?a|doing business as|f/?k/?a|formerly)\b", value, maxsplit=1, flags=re.I)[0]
    tokens = [token for token in normalize_name(value).split() if token not in LEGAL_WORDS]
    return " ".join(tokens)


def stable_key(source: str, external_id: str) -> str:
    digest = hashlib.sha256(external_id.encode("utf-8")).hexdigest()[:24]
    return f"{source}:{digest}"


def domain_from_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        host = urlparse(value if "://" in value else f"https://{value}").hostname
        if not host:
            return None
        return host.lower().removeprefix("www.")
    except ValueError:
        return None


SECOND_LEVEL_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "com.au", "net.au", "org.au", "co.nz", "co.jp", "co.kr", "co.in",
    "com.br", "com.mx", "com.sg", "com.hk", "com.tr", "com.cn", "co.il", "co.za", "com.ng", "com.ar",
    "com.co", "com.my", "com.ph", "com.pk", "com.eg", "com.sa", "co.id", "com.vn", "com.tw",
}


def registrable_domain(value: str | None) -> str | None:
    """Best-effort eTLD+1 without the public-suffix list (covers common ccTLD forms)."""
    domain = domain_from_url(value)
    if not domain:
        return None
    labels = domain.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in SECOND_LEVEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:]) if len(labels) >= 2 else domain


def canonical_url(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value or " " in value:
        return None
    candidate = value if "://" in value else f"https://{value}"
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or "." not in parsed.hostname:
        return None
    return candidate


def parse_date(value: str | None):
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError, OverflowError):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None


def number(value: str | int | float | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


class RateLimiter:
    def __init__(self, requests_per_second: float):
        self.interval = 1.0 / requests_per_second
        self.last_request = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            remaining = self.interval - (time.monotonic() - self.last_request)
            if remaining > 0:
                time.sleep(remaining)
            self.last_request = time.monotonic()


# --- Location normalization -------------------------------------------------

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana",
    "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico",
}

COUNTRY_ALIASES = {
    "usa": "United States", "us": "United States", "u s": "United States", "u s a": "United States",
    "united states": "United States", "united states of america": "United States", "america": "United States",
    "uk": "United Kingdom", "u k": "United Kingdom", "great britain": "United Kingdom", "england": "United Kingdom",
    "scotland": "United Kingdom", "wales": "United Kingdom", "northern ireland": "United Kingdom",
    "uae": "United Arab Emirates", "u a e": "United Arab Emirates", "south korea": "South Korea",
    "korea": "South Korea", "republic of korea": "South Korea", "the netherlands": "Netherlands",
    "holland": "Netherlands", "hong kong sar": "Hong Kong", "czechia": "Czech Republic",
    "canada federal level": "Canada", "turkiye": "Turkey", "russian federation": "Russia",
}


KNOWN_COUNTRIES = {
    "United States", "United Kingdom", "Canada", "India", "Germany", "France", "Mexico", "Nigeria",
    "Singapore", "Israel", "Brazil", "Australia", "Spain", "Netherlands", "Sweden", "Switzerland",
    "Indonesia", "Kenya", "Colombia", "Argentina", "Chile", "Peru", "Pakistan", "Egypt", "South Africa",
    "Ireland", "Italy", "Portugal", "Poland", "Estonia", "Finland", "Denmark", "Norway", "Belgium",
    "Austria", "Czech Republic", "Romania", "Ukraine", "Turkey", "United Arab Emirates", "Saudi Arabia",
    "Japan", "South Korea", "China", "Hong Kong", "Taiwan", "Vietnam", "Philippines", "Thailand",
    "Malaysia", "Bangladesh", "New Zealand", "Ghana", "Ethiopia", "Rwanda", "Uganda", "Tanzania",
    "Morocco", "Tunisia", "Lithuania", "Latvia", "Greece", "Hungary", "Bulgaria", "Croatia", "Serbia",
    "Luxembourg", "Iceland", "Cyprus", "Malta", "Uruguay", "Ecuador", "Guatemala", "Costa Rica",
    "Dominican Republic", "Puerto Rico", "Cayman Islands", "Bermuda", "Jordan", "Lebanon", "Qatar",
    "Bahrain", "Kuwait", "Sri Lanka", "Nepal", "Russia",
}


def smart_title(value: str | None) -> str | None:
    """Title-case ALL-CAPS strings from filings ("SAN FRANCISCO" -> "San Francisco")."""
    if not value:
        return value
    value = value.strip()
    if value.upper() != value or not any(ch.isalpha() for ch in value):
        return value
    words = []
    for word in value.lower().split():
        words.append("-".join(part[:1].upper() + part[1:] for part in word.split("-")))
    return " ".join(words)


def normalize_country(value: str | None) -> str | None:
    if not value:
        return None
    first = value.split(";")[0].strip()
    first = re.sub(r"\s*\(.*?\)\s*", " ", first).strip(" ,")
    if not first or first.lower() == "remote":
        return None
    alias = COUNTRY_ALIASES.get(normalize_name(first))
    if alias:
        return alias
    if first.upper() in US_STATES:
        return "United States"
    return smart_title(first)


def normalize_state(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    return US_STATES.get(value.upper(), smart_title(value))


def split_location(location: str | None) -> dict[str, object]:
    """Parse "San Francisco, CA, USA; Remote" style strings."""
    result: dict[str, object] = {"city": None, "state": None, "country": None, "is_remote": None}
    if not location:
        return result
    segments = [segment.strip() for segment in location.split(";") if segment.strip()]
    result["is_remote"] = any(segment.lower().startswith("remote") for segment in segments) or None
    primary = next((segment for segment in segments if not segment.lower().startswith("remote")), "")
    parts = [part.strip() for part in primary.split(",") if part.strip()]
    if not parts:
        return result
    if len(parts) == 1:
        country = normalize_country(parts[0])
        if country in KNOWN_COUNTRIES:
            result["country"] = country
            if parts[0].upper() in US_STATES:
                result["state"] = normalize_state(parts[0])
        else:
            result["city"] = parts[0]
        return result
    result["city"] = parts[0]
    country = normalize_country(parts[-1])
    result["country"] = country
    if len(parts) >= 3:
        result["state"] = normalize_state(parts[1]) if country == "United States" else parts[1]
    elif parts[-1].upper() in US_STATES:
        result["state"] = normalize_state(parts[-1])
    return result


BATCH_RE = re.compile(r"\b(winter|summer|spring|fall|autumn|[wsfx])\s*'?(\d{2}|\d{4})\b", re.I)


def batch_year(batch: str | None) -> int | None:
    """'Summer 2009' / 'S09' / 'W24' -> 2009 / 2009 / 2024."""
    if not batch:
        return None
    match = BATCH_RE.search(batch)
    if not match:
        return None
    year = int(match.group(2))
    return year + 2000 if year < 100 else year


# --- Entity classification --------------------------------------------------

FUND_NAME_RE = re.compile(
    r"\b(fund|funds|feeder|offshore|onshore|master|co-?invest(?:ment)?|spv|series\s+[a-z0-9]+\s+of|"
    r"l\.?p\.?|lp|partners|investors|investments?|capital\s+(?:partners|fund|holdings)|"
    r"opportunit(?:y|ies)|portfolio|income|yield|trust|reit|acquisition\s+corp)\b",
    re.I,
)
REAL_ESTATE_NAME_RE = re.compile(
    r"\b(apartments?|properties|property|realty|real\s+estate|residences?|lofts?|villas?|commons|"
    r"plaza|tower|storage|hotel|hospitality|multifamily|housing|homes|land|timberland|dst)\b",
    re.I,
)
REAL_ESTATE_INDUSTRIES = {
    "other real estate", "commercial", "residential", "reits and finance", "construction",
    "lodging and conventions",
}
FINANCIAL_INDUSTRIES = {
    "pooled investment fund", "investing", "other banking and financial services", "commercial banking",
    "investment banking", "insurance", "health insurance",
}


def classify_entity(name: str, industry: str | None, source_name: str | None) -> str:
    """Rough company type used for filtering: startup, investment_vehicle, real_estate, other."""
    source = (source_name or "").lower()
    if "y combinator" in source:
        return "startup"
    industry_key = (industry or "").strip().lower()
    if industry_key in FINANCIAL_INDUSTRIES or FUND_NAME_RE.search(name):
        return "investment_vehicle"
    if industry_key in REAL_ESTATE_INDUSTRIES or REAL_ESTATE_NAME_RE.search(name):
        return "real_estate"
    if "sec" in source and re.search(r"\b(?:holdings?|ventures?)\s+(?:[ivx]+|\d+)\b", name, re.I):
        return "investment_vehicle"
    if "sec" in source and industry_key in {
        "restaurants", "retailing", "oil and gas", "coal mining", "electric utilities", "agriculture",
        "airlines and airports", "tourism and travel services", "other travel", "travel",
    }:
        return "other"
    return "startup"
