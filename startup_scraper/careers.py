"""Careers-page detection.

A company "has a careers page" when its website links to (or serves) a jobs page, or embeds a
hosted applicant-tracking board. Hosted boards (Greenhouse, Lever, Ashby, ...) expose public,
keyless JSON APIs, which gives an open-job count for free.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlparse

from .http import WebClient, resolves
from .page import PageInfo, homepage, path_is_root
from .util import registrable_domain


CAREER_TEXT_RE = re.compile(
    r"\b(careers?|jobs?|join\s+(?:us|our\s+team|the\s+team)|work\s+(?:with|for|at)\s+us|"
    r"we(?:'|’)?re\s+hiring|now\s+hiring|open\s+(?:roles|positions|jobs)|vacanc(?:y|ies)|"
    r"karriere|carri[eè]res?|empleos?|trabaja\s+con\s+nosotros|vacatures|lavora\s+con\s+noi)\b",
    re.I,
)
CAREER_PATH_RE = re.compile(
    r"/(?:[a-z]{2}(?:-[a-z]{2})?/)?(careers?|jobs?|join(?:-us|-our-team|-the-team)?|work-with-us|"
    r"hiring|vacancies|open-positions|open-roles|karriere|carrieres?|vacatures|empleo)(?:[/?#.]|$)",
    re.I,
)
NOT_CAREERS_RE = re.compile(r"jobs?-to-be-done|/blog/|/news/|/press/|/tag/|/category/|steve-jobs", re.I)
SOFT_404_RE = re.compile(r"\b(404|page not found|not found|doesn(?:'|’)t exist|no longer available)\b", re.I)
PROBE_PATHS = ("/careers", "/jobs", "/join-us", "/company/careers", "/about/careers", "/join")

# (provider, regex with the board slug in group 1)
ATS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.I))
    for name, pattern in (
        ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=)?([a-z0-9_-]+)"),
        ("lever", r"jobs\.(?:eu\.)?lever\.co/([a-z0-9_.-]+)"),
        ("ashby", r"jobs\.ashbyhq\.com/([a-z0-9_.%-]+)"),
        ("workable", r"apply\.workable\.com/([a-z0-9_-]+)"),
        ("smartrecruiters", r"(?:careers|jobs)\.smartrecruiters\.com/([a-z0-9_-]+)"),
        ("recruitee", r"//([a-z0-9-]+)\.recruitee\.com"),
        ("teamtailor", r"//([a-z0-9-]+)\.teamtailor\.com"),
        ("personio", r"//([a-z0-9-]+)\.jobs\.personio\.(?:de|com)"),
        ("bamboohr", r"//([a-z0-9-]+)\.bamboohr\.com/(?:careers|jobs)"),
        ("breezy", r"//([a-z0-9-]+)\.breezy\.hr"),
        ("jazzhr", r"//([a-z0-9-]+)\.applytojob\.com"),
        ("workday", r"//([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com"),
        ("rippling", r"ats\.rippling\.com/([a-z0-9_-]+)"),
        ("jobvite", r"jobs\.jobvite\.com/([a-z0-9_-]+)"),
        ("icims", r"//(?:careers-)?([a-z0-9-]+)\.icims\.com"),
        ("pinpoint", r"//([a-z0-9-]+)\.pinpointhq\.com"),
        ("dover", r"app\.dover\.(?:io|com)/(?:apply|jobs)/([a-z0-9_-]+)"),
        ("wellfound", r"wellfound\.com/company/([a-z0-9_-]+)/jobs"),
        ("yc", r"ycombinator\.com/companies/([a-z0-9_-]+)/jobs"),
        ("join", r"join\.com/companies/([a-z0-9_-]+)"),
        ("homerun", r"//([a-z0-9-]+)\.homerun\.co"),
    )
)
IGNORED_ATS_SLUGS = {"embed", "js", "api", "v1", "jobs", "www", "careers", "apply", "job_board"}


@dataclass(slots=True)
class CareersResult:
    has_careers_page: bool
    careers_url: str | None = None
    provider: str | None = None
    open_jobs: int | None = None


def find_ats(text: str) -> tuple[str, str, str] | None:
    """Returns (provider, slug, matched url) for the first hosted job board referenced."""
    for provider, pattern in ATS_PATTERNS:
        for match in pattern.finditer(text):
            slug = match.group(1).strip(".-_").lower()
            if slug and slug not in IGNORED_ATS_SLUGS:
                start = text.rfind("http", max(0, match.start() - 12), match.start() + 1)
                url = _board_url(provider, slug) or (text[start:match.end()] if start >= 0 else match.group(0))
                return provider, slug, url
    return None


def _board_url(provider: str, slug: str) -> str | None:
    return {
        "greenhouse": f"https://job-boards.greenhouse.io/{slug}",
        "lever": f"https://jobs.lever.co/{slug}",
        "ashby": f"https://jobs.ashbyhq.com/{slug}",
        "workable": f"https://apply.workable.com/{slug}/",
        "smartrecruiters": f"https://careers.smartrecruiters.com/{slug}",
        "recruitee": f"https://{slug}.recruitee.com/",
        "teamtailor": f"https://{slug}.teamtailor.com/jobs",
        "personio": f"https://{slug}.jobs.personio.de/",
        "breezy": f"https://{slug}.breezy.hr/",
        "jazzhr": f"https://{slug}.applytojob.com/",
        "yc": f"https://www.ycombinator.com/companies/{slug}/jobs",
    }.get(provider)


def careers_links(page: PageInfo) -> list[tuple[str, bool]]:
    """Same-site links that look like a careers page, best first, with whether the link
    text itself says "Careers"/"Jobs" (a labelled link to an on-page section counts)."""
    site = registrable_domain(page.base_url)
    ranked: dict[str, tuple[int, bool]] = {}
    for url, text in page.links:
        if not url.startswith("http") or NOT_CAREERS_RE.search(url):
            continue
        if registrable_domain(url) != site:
            continue
        parsed = urlparse(url)
        score = 0
        if CAREER_PATH_RE.search(parsed.path or "/"):
            score += 2
        if parsed.hostname and parsed.hostname.split(".")[0] in {"careers", "jobs", "career", "work"}:
            score += 2
        labelled = bool(text) and len(text) <= 60 and bool(CAREER_TEXT_RE.search(text))
        if labelled:
            score += 2
        if score:
            clean = url.split("#")[0]
            previous = ranked.get(clean, (0, False))
            ranked[clean] = (max(score, previous[0]), labelled or previous[1])
    ordered = sorted(ranked.items(), key=lambda item: -item[1][0])[:4]
    return [(url, labelled) for url, (_, labelled) in ordered]


class CareersDetector:
    def __init__(self, client: WebClient):
        self.client = client

    def detect(self, home: PageInfo) -> CareersResult:
        ats = find_ats(" ".join([home.raw_html[:1_500_000], *home.frames]))
        careers_url: str | None = None

        for candidate, labelled in careers_links(home):
            page = self._careers_page(candidate, home.base_url, labelled=labelled)
            if page is not None:
                careers_url = page.base_url
                ats = ats or find_ats(" ".join([page.raw_html[:1_500_000], *page.frames]))
                break

        if careers_url is None and ats is None:
            careers_url, ats = self._probe(home.base_url)

        if careers_url is None and ats is None:
            return CareersResult(has_careers_page=False)

        provider, slug, board_url = ats if ats else ("website", "", "")
        return CareersResult(
            has_careers_page=True,
            careers_url=careers_url or board_url,
            provider=provider,
            open_jobs=self.job_count(provider, slug) if ats else None,
        )

    def _probe(self, base_url: str) -> tuple[str | None, tuple[str, str, str] | None]:
        root = homepage(base_url).rstrip("/")
        site = registrable_domain(base_url)
        probes: list[tuple[str, bool]] = [(root + path, False) for path in PROBE_PATHS[:4]]
        probes += [(f"https://{sub}.{site}/", True) for sub in ("careers", "jobs") if site]

        def attempt(probe: tuple[str, bool]) -> PageInfo | None:
            url, is_subdomain = probe
            if is_subdomain and not resolves(urlparse(url).hostname or ""):
                return None
            return self._careers_page(url, base_url, allow_root=is_subdomain)

        with ThreadPoolExecutor(max_workers=len(probes)) as pool:
            pages = list(pool.map(attempt, probes))
        for page in pages:  # PROBE_PATHS order is the preference order
            if page is not None:
                return page.base_url, find_ats(" ".join([page.raw_html[:1_500_000], *page.frames]))
        return None, None

    def _careers_page(
        self, url: str, home_url: str, *, allow_root: bool = False, labelled: bool = False
    ) -> PageInfo | None:
        result = self.client.fetch(url)
        if not result.ok or ("html" not in result.content_type.lower() and result.content_type):
            return None
        final = result.url
        # A redirect back to the homepage means the path does not exist (soft 404), unless a
        # link labelled "Careers" deliberately points at a section of the homepage.
        if not allow_root and not labelled and path_is_root(final) and registrable_domain(final) == registrable_domain(home_url):
            return None
        page = PageInfo.parse(final, result.text())
        if SOFT_404_RE.search(page.title) and not CAREER_TEXT_RE.search(page.title):
            return None
        headline = f"{page.title} {' '.join(page.h1)}"
        if CAREER_TEXT_RE.search(headline) or find_ats(" ".join([page.raw_html[:1_500_000], *page.frames])):
            return page
        parsed = urlparse(final)
        careers_location = bool(CAREER_PATH_RE.search(parsed.path or "/")) or (
            (parsed.hostname or "").split(".")[0] in {"careers", "jobs", "career"}
        )
        if (careers_location or labelled) and CAREER_TEXT_RE.search(page.text[:20_000]):
            return page
        return None

    def job_count(self, provider: str, slug: str) -> int | None:
        """Open-job count from public, keyless ATS APIs."""
        if not slug:
            return None
        if provider == "greenhouse":
            data = self.client.fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
            if isinstance(data, dict):
                meta = data.get("meta") or {}
                return int(meta.get("total")) if isinstance(meta.get("total"), int) else len(data.get("jobs") or [])
        elif provider == "lever":
            data = self.client.fetch_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
            if data is None:
                data = self.client.fetch_json(f"https://api.eu.lever.co/v0/postings/{slug}?mode=json")
            if isinstance(data, list):
                return len(data)
        elif provider == "ashby":
            data = self.client.fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
            if isinstance(data, dict):
                return len(data.get("jobs") or [])
        elif provider == "workable":
            data = self.client.fetch_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
            if isinstance(data, dict):
                return len(data.get("jobs") or [])
        elif provider == "recruitee":
            data = self.client.fetch_json(f"https://{slug}.recruitee.com/api/offers/")
            if isinstance(data, dict):
                return len(data.get("offers") or [])
        elif provider == "smartrecruiters":
            data = self.client.fetch_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1")
            if isinstance(data, dict) and isinstance(data.get("totalFound"), int):
                return data["totalFound"]
        return None
