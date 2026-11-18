"""Keyless website discovery.

Search engines block automated queries (robots.txt / bot challenges), so discovery relies on
sources that are meant to be read by programs or that name the company directly, and every
candidate is verified against the company's own homepage before it is accepted:

1. the source profile (YC company page JSON)
2. the funding-news article that mentioned the company (outbound links)
3. Wikidata (official website property)
4. domain guessing from the company name + DNS + homepage verification
5. optional: an official search API when a key is configured (BRAVE_SEARCH_API_KEY)
"""

from __future__ import annotations

import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import quote, quote_plus, urlparse

from .http import WebClient, resolves
from .page import PageInfo, homepage, looks_parked
from .util import core_name, domain_from_url, normalize_name, registrable_domain


BLOCKED_DOMAINS = {
    "linkedin.com", "crunchbase.com", "bloomberg.com", "pitchbook.com", "facebook.com", "instagram.com",
    "x.com", "twitter.com", "youtube.com", "wikipedia.org", "wikimedia.org", "wikidata.org", "sec.gov",
    "opencorporates.com", "zoominfo.com", "tracxn.com", "cbinsights.com", "glassdoor.com", "indeed.com",
    "ycombinator.com", "techcrunch.com", "crunchbase.news", "eu-startups.com", "tech.eu", "venturebeat.com",
    "reuters.com", "forbes.com", "businessinsider.com", "medium.com", "substack.com", "github.com",
    "apple.com", "google.com", "play.google.com", "apps.apple.com", "tiktok.com", "reddit.com",
    "producthunt.com", "angel.co", "wellfound.com", "dealroom.co", "owler.com", "dnb.com", "bizapedia.com",
    "buzzfile.com", "manta.com", "yelp.com", "bbb.org", "prnewswire.com", "businesswire.com",
    "globenewswire.com", "accesswire.com", "einpresswire.com", "finsmes.com", "axios.com", "wsj.com",
    "nytimes.com", "ft.com", "cnbc.com", "theinformation.com", "sifted.eu", "siliconangle.com",
    "geekwire.com", "fortune.com", "theverge.com", "wired.com", "fiercebiotech.com", "news.crunchbase.com",
    "gstatic.com", "googleapis.com", "cloudflare.com", "wp.com", "wordpress.com", "gravatar.com",
    "doubleclick.net", "bit.ly", "lnkd.in", "t.co", "mailchimp.com", "eepurl.com", "typeform.com",
    "calendly.com", "hubspot.com", "zendesk.com", "intercom.io", "vimeo.com", "soundcloud.com",
    "spotify.com", "podcasts.apple.com", "threads.net", "bsky.app", "mastodon.social", "discord.gg",
    "discord.com", "t.me", "whatsapp.com", "amazon.com", "amzn.to", "shopify.com", "notion.so",
}

GENERIC_TOKENS = {
    "technologies", "technology", "tech", "labs", "lab", "ai", "health", "healthcare", "medical", "med",
    "systems", "solutions", "software", "bio", "biosciences", "therapeutics", "pharma", "pharmaceuticals",
    "capital", "partners", "group", "global", "international", "services", "ventures", "studio", "studios",
    "data", "network", "networks", "energy", "digital", "media", "robotics", "financial", "finance", "app",
    "apps", "holdings", "industries", "enterprises", "consulting", "management", "sciences", "science",
    "innovations", "innovation", "products", "brands", "foods", "america", "usa", "us", "new", "and", "of",
    "for", "the", "a", "an", "hq", "io", "co", "inc", "llc", "ltd", "corp", "company", "online", "cloud",
    "platform", "security", "devices", "diagnostics", "materials", "intelligence", "analytics", "automation",
}

ABBREVIATIONS = {
    "medical": ["med"], "technologies": ["tech"], "technology": ["tech"], "laboratories": ["labs"],
    "laboratory": ["lab"], "pharmaceuticals": ["pharma"], "pharmaceutical": ["pharma"],
    "therapeutics": ["tx", "bio"], "international": ["intl"], "biosciences": ["bio"], "systems": ["sys"],
    "solutions": [""], "software": [""], "industries": [""], "holdings": [""], "group": [""],
    "incorporated": [""], "enterprises": [""], "services": [""], "networks": ["net"], "robotics": ["robotics"],
    "diagnostics": ["dx"], "health": ["health", ""], "healthcare": ["health"], "analytics": [""],
}

COUNTRY_TLDS = {
    "United Kingdom": ["co.uk", "uk"], "Germany": ["de"], "France": ["fr"], "Canada": ["ca"], "India": ["in", "co.in"],
    "Singapore": ["sg", "com.sg"], "Australia": ["com.au"], "Israel": ["co.il"], "Netherlands": ["nl"],
    "Sweden": ["se"], "Spain": ["es"], "Italy": ["it"], "Brazil": ["com.br"], "Mexico": ["mx", "com.mx"],
    "Nigeria": ["ng", "com.ng"], "Switzerland": ["ch"], "Ireland": ["ie"], "Denmark": ["dk"], "Norway": ["no"],
    "Finland": ["fi"], "Estonia": ["ee"], "Poland": ["pl"], "Portugal": ["pt"], "Belgium": ["be"],
    "Austria": ["at"], "Japan": ["jp", "co.jp"], "Kenya": ["co.ke"], "South Africa": ["co.za"],
    "Indonesia": ["id", "co.id"], "Colombia": ["co", "com.co"], "Argentina": ["com.ar"], "Chile": ["cl"],
    "United Arab Emirates": ["ae"], "Pakistan": ["pk"], "Egypt": ["com.eg"], "Turkey": ["com.tr"],
}

STOPWORDS = {
    "about", "their", "which", "these", "those", "there", "where", "while", "would", "could", "should",
    "other", "using", "based", "company", "companies", "platform", "service", "services", "product",
    "products", "business", "businesses", "customers", "people", "world", "first", "through", "including",
    "helps", "build", "built", "making", "provides", "provider", "solution", "solutions", "within",
}


@dataclass(slots=True)
class CompanyProfile:
    """What discovery needs to know about a company."""

    name: str
    city: str | None = None
    state: str | None = None
    country: str | None = None
    description: str | None = None
    core: str = ""
    tokens: list[str] = field(default_factory=list)
    distinctive: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.core = core_name(self.name) or normalize_name(self.name)
        self.tokens = [token for token in self.core.split() if token]
        self.distinctive = [token for token in self.tokens if token not in GENERIC_TOKENS and len(token) >= 2]

    @property
    def compact(self) -> str:
        return self.core.replace(" ", "")

    @property
    def is_weak_name(self) -> bool:
        """Short single-word names (\"Couple\", \"Treat\") collide with unrelated sites."""
        return len(self.distinctive) <= 1 and len(self.compact) <= 7

    def description_keywords(self) -> list[str]:
        words = re.findall(r"[a-z]{5,}", normalize_name(self.description or ""))
        seen: list[str] = []
        for word in words:
            if word not in STOPWORDS and word not in self.tokens and word not in seen:
                seen.append(word)
        return seen[:20]


@dataclass(slots=True)
class VerifiedSite:
    url: str
    page: PageInfo
    score: int


@dataclass(slots=True)
class ProfileFacts:
    """Facts read from a structured source profile (YC page, Wikidata)."""

    website: str | None = None
    founded_year: int | None = None
    founded_on: str | None = None
    jobs_count: int | None = None
    jobs_url: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


def is_blocked(url: str) -> bool:
    domain = domain_from_url(url) or ""
    return not domain or any(domain == blocked or domain.endswith(f".{blocked}") for blocked in BLOCKED_DOMAINS)


def domain_label(url: str) -> str:
    registrable = registrable_domain(url) or ""
    return registrable.split(".")[0] if registrable else ""


def score_page(company: CompanyProfile, url: str, page: PageInfo) -> int:
    """How strongly a fetched page looks like the company's own homepage."""
    if looks_parked(page):
        return -10
    brand = normalize_name(page.brand_text)
    brand_tokens = set(brand.split())
    body = normalize_name(page.text[:30_000])
    body_tokens = set(body.split())
    compact_brand = brand.replace(" ", "")
    compact_body = body.replace(" ", "")
    tokens = company.tokens
    score = 0
    if company.compact and len(company.compact) >= 3 and company.compact in compact_brand:
        score += 4
    elif tokens and all(token in brand_tokens for token in tokens):
        score += 3
    elif company.compact and len(company.compact) >= 4 and company.compact in compact_body:
        score += 2
    elif tokens and all(token in body_tokens for token in tokens):
        score += 1
    elif company.distinctive and all(token in brand_tokens for token in company.distinctive):
        score += 1
    label = domain_label(url)
    if label and label == company.compact:
        score += 2
    elif label and company.distinctive and label.startswith(company.distinctive[0]) and len(company.distinctive[0]) >= 4:
        score += 1
    context = context_score(company, page)
    score += context
    if company.is_weak_name and context == 0:
        # A bare common word matching a domain proves little without corroborating context.
        score = min(score, 3)
    return score


def context_score(company: CompanyProfile, page: PageInfo) -> int:
    """Evidence beyond the name: the company's city/state or description words on the page."""
    body = normalize_name(f"{page.description} {page.text[:30_000]}")
    body_tokens = set(body.split())
    context = 0
    for place in (company.city, company.state):
        if place and len(place) >= 4 and normalize_name(place) in body:
            context += 1
            break
    keywords = company.description_keywords()
    if keywords and sum(1 for word in keywords if word in body_tokens) >= min(4, max(2, len(keywords) // 3)):
        context += 1
    return context


class WebsiteDiscovery:
    def __init__(self, client: WebClient, *, brave_api_key: str | None = None):
        self.client = client
        self.brave_api_key = brave_api_key if brave_api_key is not None else os.getenv("BRAVE_SEARCH_API_KEY")

    # -- verification ---------------------------------------------------------
    def load(self, url: str) -> tuple[PageInfo | None, str | None]:
        """Fetch and parse a page. Returns (page, error)."""
        result = self.client.fetch(url)
        if not result.ok and url.startswith("https://") and result.status == 0 and "robots" not in (result.error or ""):
            result = self.client.fetch("http://" + url.removeprefix("https://"))
        if not result.ok:
            return None, result.error or f"HTTP {result.status}"
        if "html" not in result.content_type.lower() and result.content_type:
            return None, f"not html ({result.content_type.split(';')[0]})"
        return PageInfo.parse(result.url, result.text()), None

    def verify(
        self, company: CompanyProfile, url: str, *, threshold: int, require_context: bool = False
    ) -> VerifiedSite | None:
        if is_blocked(url):
            return None
        page, _ = self.load(homepage(url))
        if page is None:
            return None
        score = score_page(company, page.base_url, page)
        if require_context and context_score(company, page) == 0:
            return None
        return VerifiedSite(page.base_url, page, score) if score >= threshold else None

    def verify_best(
        self, company: CompanyProfile, urls: list[str], *, threshold: int, require_context: bool = False
    ) -> VerifiedSite | None:
        """Verify candidates concurrently; best score wins, earlier candidates win ties."""
        urls = [url for url in dict.fromkeys(urls) if not is_blocked(url)]
        if not urls:
            return None
        with ThreadPoolExecutor(max_workers=min(4, len(urls))) as pool:
            results = list(pool.map(
                lambda url: self.verify(company, url, threshold=threshold, require_context=require_context), urls
            ))
        best: VerifiedSite | None = None
        for site in results:
            if site and (best is None or site.score > best.score):
                best = site
        return best

    # -- candidate sources ------------------------------------------------------
    def yc_profile(self, profile_url: str) -> ProfileFacts | None:
        if "ycombinator.com/companies/" not in profile_url:
            return None
        result = self.client.fetch(profile_url)
        if not result.ok:
            return None
        match = re.search(r'data-page="([^"]+)"', result.text())
        if not match:
            return None
        try:
            data = json.loads(html.unescape(match.group(1)))
        except json.JSONDecodeError:
            return None
        props = data.get("props") or {}
        company = props.get("company") or {}
        postings = props.get("jobPostings")
        year = company.get("year_founded")
        facts = ProfileFacts(
            website=company.get("website") or None,
            founded_year=int(year) if isinstance(year, int) or (isinstance(year, str) and year.isdigit()) else None,
            jobs_count=len(postings) if isinstance(postings, list) else None,
            jobs_url=props.get("jobsUrl") or None,
        )
        for key in ("linkedin_url", "twitter_url", "github_url", "cb_url"):
            if company.get(key):
                facts.extra[key] = company[key]
        return facts

    def article_candidates(self, company: CompanyProfile, article_url: str) -> list[str]:
        """Outbound links in the funding article whose domain or anchor text names the company."""
        if not article_url or not article_url.startswith("http"):
            return []
        page, _ = self.load(article_url)
        if page is None:
            return []
        article_site = registrable_domain(article_url)
        scored: dict[str, int] = {}
        for url, text in page.links:
            if registrable_domain(url) == article_site or is_blocked(url):
                continue
            label = domain_label(url)
            if not label:
                continue
            score = 0
            if label == company.compact:
                score += 3
            elif len(label) >= 4 and (company.compact.startswith(label) or label.startswith(company.compact)):
                score += 2
            elif company.distinctive and len(company.distinctive[0]) >= 4 and company.distinctive[0] in label:
                score += 1
            if normalize_name(text) == company.core:
                score += 2
            if score >= 2:
                key = homepage(url)
                scored[key] = max(score, scored.get(key, 0))
        return [url for url, _ in sorted(scored.items(), key=lambda item: -item[1])[:3]]

    def wikidata(self, company: CompanyProfile) -> ProfileFacts | None:
        if len(company.compact) < 3:
            return None
        search = self.client.fetch_json(
            "https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&language=en&type=item"
            f"&limit=7&search={quote(company.name[:100])}"
        )
        if not search:
            return None
        ids = [
            item["id"] for item in search.get("search", [])
            if core_name(item.get("label", "")) == company.core or normalize_name(item.get("label", "")) == normalize_name(company.name)
        ]
        if not ids:
            return None
        entities = self.client.fetch_json(
            "https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&props=claims|descriptions"
            f"&languages=en&ids={'|'.join(ids[:5])}"
        )
        if not entities:
            return None
        best: tuple[int, ProfileFacts] | None = None
        for entity_id in ids:
            entity = (entities.get("entities") or {}).get(entity_id) or {}
            claims = entity.get("claims") or {}
            websites = [_claim_value(claim) for claim in claims.get("P856", [])]
            websites = [value for value in websites if isinstance(value, str)]
            inception = next((_claim_value(claim) for claim in claims.get("P571", [])), None)
            description = ((entity.get("descriptions") or {}).get("en") or {}).get("value", "").lower()
            rank = 0
            if websites and any(domain_label(site) == company.compact for site in websites):
                rank += 3
            if re.search(r"company|startup|business|firm|manufacturer|developer|provider|platform|maker", description):
                rank += 2
            if websites:
                rank += 1
            if rank < 2:
                continue
            facts = ProfileFacts(website=websites[0] if websites else None, extra={"wikidata_id": entity_id})
            if isinstance(inception, dict):
                facts.founded_year, facts.founded_on = _wikidata_time(inception)
            if best is None or rank > best[0]:
                best = (rank, facts)
        return best[1] if best else None

    def guess_domains(self, company: CompanyProfile, country: str | None) -> list[str]:
        names = candidate_labels(company)
        tlds = ["com", "io", "ai", "co", "app", "tech"]
        if any(token in {"health", "healthcare", "medical", "med", "care"} for token in company.tokens):
            tlds.append("health")
        if any(token in {"bio", "biosciences", "therapeutics", "biotech"} for token in company.tokens):
            tlds.append("bio")
        tlds = COUNTRY_TLDS.get(country or "", []) + tlds
        hosts: list[str] = []
        for index, label in enumerate(names):
            for tld in tlds if index < 3 else ["com"]:
                host = f"{label}.{tld}"
                if host not in hosts:
                    hosts.append(host)
        hosts = hosts[:32]
        with ThreadPoolExecutor(max_workers=16) as pool:
            live = [host for host, ok in zip(hosts, pool.map(resolves, hosts)) if ok]
        return [f"https://{host}/" for host in live[:8]]

    def brave_search(self, company: CompanyProfile) -> list[str]:
        """Official Brave Search API (paid, with a monthly credit). Inert unless a key is configured."""
        if not self.brave_api_key:
            return []
        query = " ".join(part for part in (f'"{company.core}"', company.city or "", "official website") if part)
        result = self.client.fetch(
            f"https://api.search.brave.com/res/v1/web/search?count=8&q={quote_plus(query)}",
            accept="application/json",
            respect_robots=False,
            headers={"X-Subscription-Token": self.brave_api_key},
        )
        if not result.ok:
            return []
        try:
            items = (result.json().get("web") or {}).get("results") or []
        except (json.JSONDecodeError, AttributeError):
            return []
        urls: list[str] = []
        for item in items:
            url = item.get("url") or ""
            if url.startswith("http") and not is_blocked(url):
                key = homepage(url)
                if key not in urls:
                    urls.append(key)
        return urls[:4]


def candidate_labels(company: CompanyProfile) -> list[str]:
    """Domain labels a company with this name plausibly uses, most likely first."""
    tokens = company.tokens
    if not tokens:
        return []
    labels: list[str] = []

    def add(value: str) -> None:
        value = re.sub(r"[^a-z0-9-]", "", value).strip("-")
        if 3 <= len(value) <= 40 and value not in labels:
            labels.append(value)

    add("".join(tokens))
    add("".join(ABBREVIATIONS.get(token, [token])[0] for token in tokens))
    for index, token in enumerate(tokens):
        for alternative in ABBREVIATIONS.get(token, [])[1:]:
            add("".join(tokens[:index] + [alternative] + tokens[index + 1:]))
    if len(tokens) >= 3:
        add("".join(tokens[:2]))
    if len(tokens) >= 2:
        add("-".join(tokens))
        if company.distinctive and len(company.distinctive[0]) >= 5:
            add(company.distinctive[0])
    if len(tokens) == 1 or len("".join(tokens)) <= 8:
        base = "".join(tokens)
        for affix in (f"get{base}", f"try{base}", f"{base}hq", f"{base}app", f"use{base}", f"join{base}", f"{base}labs"):
            add(affix)
    return labels[:12]


def _claim_value(claim: dict) -> object:
    return ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")


def _wikidata_time(value: dict) -> tuple[int | None, str | None]:
    raw = str(value.get("time", ""))
    match = re.match(r"\+?(\d{4})-(\d{2})-(\d{2})", raw)
    if not match:
        return None, None
    year, month, day = (int(part) for part in match.groups())
    precision = int(value.get("precision") or 9)
    if not 1800 <= year <= date.today().year:
        return None, None
    if precision >= 11 and month and day:
        return year, f"{year:04d}-{month:02d}-{day:02d}"
    return year, None


def origin_of(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"
