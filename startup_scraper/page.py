from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from .util import normalize_name


class PageInfo(HTMLParser):
    """Extracts the parts of an HTML page that enrichment needs, with bounded memory."""

    SKIP_TAGS = {"script", "style", "noscript", "svg", "template"}
    MAX_TEXT = 200_000

    def __init__(self, base_url: str, raw_html: str = ""):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.raw_html = raw_html
        self.title = ""
        self.meta: dict[str, str] = {}
        self.h1: list[str] = []
        self.links: list[tuple[str, str]] = []  # (absolute url, visible text)
        self.frames: list[str] = []
        self.img_alts: list[str] = []
        self.json_ld: list[str] = []
        self.text_parts: list[str] = []
        self._text_size = 0
        self._skip = 0
        self._in_title = False
        self._h1_parts: list[str] | None = None
        self._anchor: tuple[str, list[str]] | None = None
        self._ld_parts: list[str] | None = None

    @classmethod
    def parse(cls, url: str, html: str) -> "PageInfo":
        page = cls(url, html)
        try:
            page.feed(html)
            page.close()
        except Exception:  # noqa: BLE001 - malformed markup still yields partial data
            pass
        return page

    # -- HTMLParser hooks ---------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag == "meta":
            key = (values.get("property") or values.get("name") or values.get("itemprop") or "").lower()
            if key and values.get("content") and key not in self.meta:
                self.meta[key] = values["content"].strip()
        elif tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._h1_parts = []
        elif tag == "a":
            href = values.get("href", "").strip()
            if href and not href.startswith(("javascript:", "#", "tel:")):
                self._anchor = (href, [values.get("aria-label", ""), values.get("title", "")])
        elif tag == "img":
            alt = values.get("alt", "").strip()
            if alt and len(self.img_alts) < 40:
                self.img_alts.append(alt)
        elif tag == "iframe" and values.get("src"):
            self.frames.append(self._absolute(values["src"]))
        elif tag == "script":
            if values.get("type", "").lower() == "application/ld+json":
                self._ld_parts = []
            else:
                self._skip += 1
        elif tag in self.SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "h1" and self._h1_parts is not None:
            text = " ".join(" ".join(self._h1_parts).split())
            if text and len(self.h1) < 10:
                self.h1.append(text[:300])
            self._h1_parts = None
        elif tag == "a" and self._anchor is not None:
            href, parts = self._anchor
            text = " ".join(" ".join(parts).split())
            if len(self.links) < 3000:
                self.links.append((self._absolute(href), text[:200]))
            self._anchor = None
        elif tag == "script":
            if self._ld_parts is not None:
                self.json_ld.append("".join(self._ld_parts))
                self._ld_parts = None
            elif self._skip:
                self._skip -= 1
        elif tag in self.SKIP_TAGS and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._ld_parts is not None:
            self._ld_parts.append(data)
            return
        if self._skip:
            return
        if self._in_title:
            self.title += data
        if self._h1_parts is not None:
            self._h1_parts.append(data)
        if self._anchor is not None:
            self._anchor[1].append(data)
        stripped = data.strip()
        if stripped and self._text_size < self.MAX_TEXT:
            self.text_parts.append(stripped)
            self._text_size += len(stripped)

    # -- helpers ------------------------------------------------------------
    def _absolute(self, href: str) -> str:
        try:
            return urljoin(self.base_url, href)
        except ValueError:
            return href

    @property
    def text(self) -> str:
        return " ".join(self.text_parts)

    @property
    def brand_text(self) -> str:
        """Places where a site names itself: title, og tags, h1, logo alt text."""
        parts = [
            self.title,
            self.meta.get("og:site_name", ""),
            self.meta.get("og:title", ""),
            self.meta.get("application-name", ""),
            self.meta.get("twitter:title", ""),
            *self.h1[:3],
            *self.img_alts[:8],
        ]
        return " ".join(part for part in parts if part)

    @property
    def description(self) -> str:
        return self.meta.get("description") or self.meta.get("og:description") or ""


PARKED_RE = re.compile(
    r"(domain (?:name )?(?:is|may be) for sale|buy this domain|this domain is for sale|domain for sale|"
    r"make an offer on this domain|parked (?:free|domain|by)|sedoparking|parkingcrew|bodis\.com|"
    r"hugedomains|afternic|dan\.com|domainmarket|undeveloped\.com|future home of something quite cool|"
    r"this domain has expired|domain has been registered|account (?:has been )?suspended|"
    r"website (?:is )?coming soon|site is under construction|default web site page|"
    r"welcome to nginx|apache2? (?:ubuntu |debian )?default page|it works!|index of /|"
    r"web hosting (?:by|from) (?:godaddy|bluehost|hostgator))",
    re.I,
)


def looks_parked(page: PageInfo) -> bool:
    sample = f"{page.title} {page.text[:6000]}"
    if PARKED_RE.search(sample):
        return True
    # A page with almost no text and no links is not a real company site.
    return len(page.text) < 80 and len(page.links) < 3


def same_site(url: str, other: str) -> bool:
    from .util import registrable_domain

    return bool(registrable_domain(url)) and registrable_domain(url) == registrable_domain(other)


def homepage(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/"


def path_is_root(url: str) -> bool:
    return urlparse(url).path in {"", "/"} and not urlparse(url).query


def page_tokens(text: str) -> set[str]:
    return set(normalize_name(text).split())
