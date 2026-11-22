"""Company social profiles and a public contact email, read from the company's own website.

Only company pages are kept (linkedin.com/company/..., not personal /in/ profiles), and only
role addresses (hello@, careers@, ...) on the company's own domain: personal email addresses
are never collected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse

from .page import PageInfo
from .util import normalize_name, registrable_domain

LINKEDIN_RE = re.compile(r"^https?://(?:[a-z]{2,3}\.)?linkedin\.com/(company|school|showcase)/([^/?#\s]+)", re.I)
TWITTER_RE = re.compile(r"^https?://(?:www\.|mobile\.)?(?:twitter|x)\.com/(?:#!/)?@?([A-Za-z0-9_]{1,15})/?(?:[?#].*)?$", re.I)
GITHUB_RE = re.compile(r"^https?://(?:www\.)?github\.com/(?:orgs/)?([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))(?:[/?#]|$)", re.I)
EMAIL_RE = re.compile(r"\b([A-Za-z0-9._%+-]{1,64})@([A-Za-z0-9.-]+\.[A-Za-z]{2,24})\b")
# Profile URLs inside scripts/JSON on sites whose footer is rendered by JavaScript.
RAW_PROFILE_RE = re.compile(
    r"(?<![\w.-])(?:[a-z]{2,3}\.|www\.|mobile\.)?"
    r"(linkedin\.com/(?:company|school|showcase)/[A-Za-z0-9%_.-]+|(?:twitter|x)\.com/@?[A-Za-z0-9_]{1,15}(?![\w/])|"
    r"github\.com/[A-Za-z0-9-]{1,39}(?![\w-]))",
    re.I,
)
CF_EMAIL_RE = re.compile(r'(?:data-cfemail="|/cdn-cgi/l/email-protection#)([0-9a-fA-F]{6,200})')

TWITTER_RESERVED = {
    "share", "intent", "home", "hashtag", "search", "i", "login", "signup", "privacy", "tos", "explore",
    "settings", "messages", "notifications", "compose", "about", "help", "jobs", "download",
}
GITHUB_RESERVED = {
    "features", "about", "pricing", "login", "join", "sponsors", "topics", "marketplace", "explore", "site",
    "contact", "enterprise", "security", "apps", "collections", "trending", "customer-stories", "readme",
    "team", "events", "github", "settings", "notifications", "new", "search", "pulls", "issues", "orgs",
}
LINKEDIN_RESERVED = {"linkedin", "company", "school", "showcase"}

# Role mailboxes, in the order a job seeker would want them.
ROLE_MAILBOXES = (
    "careers", "jobs", "hiring", "recruiting", "talent", "people", "hr", "join", "work",
    "hello", "hi", "hey", "contact", "info", "team", "founders", "general", "office", "inquiries", "enquiries",
    "support", "help", "sales", "business", "bd", "partners", "partnerships", "press", "media", "pr",
    "marketing", "community", "admin", "investors", "ir",
)
_ROLE_RANK = {name: index for index, name in enumerate(ROLE_MAILBOXES)}
CONTACT_PATH_RE = re.compile(r"/(contact(?:-us)?|get-in-touch|kontakt|contacto|contatti|imprint|impressum)(?:[/?#.]|$)", re.I)


@dataclass(slots=True)
class Contacts:
    linkedin_url: str | None = None
    twitter_url: str | None = None
    github_url: str | None = None
    contact_email: str | None = None
    sources: dict[str, str] = field(default_factory=dict)

    def merge(self, other: "Contacts", source: str) -> None:
        """Fill fields that are still empty from `other`."""
        for key in ("linkedin_url", "twitter_url", "github_url", "contact_email"):
            value = getattr(other, key)
            if value and not getattr(self, key):
                setattr(self, key, value)
                self.sources[key] = source

    def as_patch(self) -> dict[str, str]:
        return {key: getattr(self, key) for key in ("linkedin_url", "twitter_url", "github_url", "contact_email") if getattr(self, key)}


def _with_scheme(value: str) -> str:
    """Admins type "linkedin.com/company/acme"; page links are already absolute."""
    value = value.strip()
    return f"https://{value}" if re.match(r"^(?:www\.)?[a-z0-9-]+\.[a-z]{2,}/", value, re.I) else value


def linkedin_url(url: str | None) -> str | None:
    match = LINKEDIN_RE.match(_with_scheme(url or ""))
    if not match or match.group(2).lower() in LINKEDIN_RESERVED:
        return None
    return f"https://www.linkedin.com/{match.group(1).lower()}/{unquote(match.group(2)).strip()}"


def twitter_url(url: str | None) -> str | None:
    value = (url or "").strip()
    if re.fullmatch(r"@?[A-Za-z0-9_]{1,15}", value):  # bare handle (Wikidata, YC)
        handle = value.lstrip("@")
    else:
        match = TWITTER_RE.match(_with_scheme(value))
        if not match:
            return None
        handle = match.group(1)
    if handle.lower() in TWITTER_RESERVED:
        return None
    return f"https://x.com/{handle}"


def github_url(url: str | None) -> str | None:
    value = (url or "").strip()
    if re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", value):
        org = value
    else:
        match = GITHUB_RE.match(_with_scheme(value))
        if not match:
            return None
        org = match.group(1)
    if org.lower() in GITHUB_RESERVED:
        return None
    return f"https://github.com/{org}"


def _handle(url: str) -> str:
    return normalize_name(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]).replace(" ", "")


def _named_like(url: str, compact_name: str) -> bool:
    handle = _handle(url)
    return bool(handle) and len(compact_name) >= 3 and (compact_name in handle or (len(handle) >= 4 and handle in compact_name))


def _pick(candidates: list[str], compact_name: str, *, require_name: bool = False) -> str | None:
    """The profile named like the company, else the only one on the page (a page linking several
    accounts is usually crediting partners or founders)."""
    distinct = list(dict.fromkeys(candidates))
    for url in distinct:
        if _named_like(url, compact_name):
            return url
    return distinct[0] if len(distinct) == 1 and not require_name else None


def _decode_cloudflare(hex_value: str) -> str | None:
    try:
        data = bytes.fromhex(hex_value)
    except ValueError:
        return None
    if len(data) < 2:
        return None
    key = data[0]
    try:
        return bytes(byte ^ key for byte in data[1:]).decode("utf-8")
    except UnicodeDecodeError:
        return None


def emails_on_page(page: PageInfo) -> list[str]:
    found: list[str] = []
    for url, _ in page.links:
        if url.lower().startswith("mailto:"):
            found.append(unquote(url[7:].split("?", 1)[0]))
    for match in CF_EMAIL_RE.finditer(page.raw_html or ""):
        decoded = _decode_cloudflare(match.group(1))
        if decoded:
            found.append(decoded)
    found.extend(f"{local}@{domain}" for local, domain in EMAIL_RE.findall(page.text))
    # Footers rendered by JavaScript keep their addresses in the page data.
    found.extend(f"{local}@{domain}" for local, domain in EMAIL_RE.findall(page.raw_html or ""))
    return [email.strip().strip(".").lower() for email in found if "@" in email]


def contact_email(page: PageInfo, site_url: str) -> str | None:
    """Best role address on the company's own domain."""
    site = registrable_domain(site_url)
    if not site:
        return None
    best: tuple[int, str] | None = None
    for email in emails_on_page(page):
        local, _, domain = email.partition("@")
        if registrable_domain(domain) != site or not EMAIL_RE.fullmatch(email):
            continue
        rank = _ROLE_RANK.get(re.split(r"[.+_-]", local, maxsplit=1)[0])
        if rank is None:
            continue
        if best is None or rank < best[0]:
            best = (rank, email)
    return best[1] if best else None


def contacts_from_page(page: PageInfo, site_url: str, company_name: str) -> Contacts:
    compact = normalize_name(company_name).replace(" ", "")
    linkedin: list[str] = []
    twitter: list[str] = []
    github: list[str] = []
    for url, _ in page.links:
        if not url.lower().startswith("http"):
            continue
        if value := linkedin_url(url):
            linkedin.append(value)
        elif value := twitter_url(url):
            twitter.append(value)
        elif value := github_url(url):
            github.append(value)
    found = Contacts(
        linkedin_url=_pick(linkedin, compact),
        twitter_url=_pick(twitter, compact),
        github_url=_pick(github, compact),
        contact_email=contact_email(page, site_url),
    )
    if not (found.linkedin_url and found.twitter_url and found.github_url) and page.raw_html:
        raw = {"linkedin_url": [], "twitter_url": [], "github_url": []}
        for match in RAW_PROFILE_RE.finditer(page.raw_html.replace("\\/", "/")):
            url = "https://" + match.group(1)
            for key, canonical in (("linkedin_url", linkedin_url), ("twitter_url", twitter_url), ("github_url", github_url)):
                if value := canonical(url):
                    raw[key].append(value)
                    break
        for key, candidates in raw.items():
            if not getattr(found, key):
                # Scripts mention partners' and customers' accounts too: the handle must match the name.
                setattr(found, key, _pick(candidates, compact, require_name=True))
    return found


def contact_page_url(page: PageInfo, site_url: str) -> str | None:
    site = registrable_domain(site_url)
    for url, _ in page.links:
        if registrable_domain(url) == site and CONTACT_PATH_RE.search(urlparse(url).path):
            return url.split("#", 1)[0]
    return None
