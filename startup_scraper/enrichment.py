"""Per-company enrichment: website discovery/verification, careers page, founding date."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .careers import CareersDetector, CareersResult
from .discovery import CompanyProfile, VerifiedSite, WebsiteDiscovery, score_page
from .founding import (
    FoundedFact,
    about_page_url,
    best,
    domain_registration,
    founded_rank,
    from_structured_data,
    from_text,
)
from .http import WebClient
from .models import utc_now
from .util import canonical_url, domain_from_url


DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; FundingRadarBot/1.0)"
SKIP_GUESSING_KINDS = {"investment_vehicle", "real_estate"}


@dataclass(slots=True)
class EnrichmentResult:
    company_id: str
    patch: dict[str, Any]
    log: list[str] = field(default_factory=list)
    website_found: bool = False
    careers_found: bool = False
    founded_found: bool = False
    error: str | None = None


class Enricher:
    """Keyless, best-effort enrichment. Never raises; failures are recorded on the row."""

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        *,
        client: WebClient | None = None,
        budget_seconds: float = 90,
        brave_api_key: str | None = None,
    ):
        self.client = client or WebClient(user_agent=user_agent)
        self.discovery = WebsiteDiscovery(self.client, brave_api_key=brave_api_key)
        self.careers = CareersDetector(self.client)
        self.budget_seconds = budget_seconds

    def enrich(self, row: dict[str, Any]) -> EnrichmentResult:
        try:
            return self._enrich(row)
        except Exception as exc:  # noqa: BLE001 - one bad site must not stop a batch
            return EnrichmentResult(
                company_id=row["id"],
                patch={"enriched_at": utc_now(), "enrichment_error": f"{exc.__class__.__name__}: {exc}"[:500]},
                error=str(exc),
            )

    # ------------------------------------------------------------------------
    def _enrich(self, row: dict[str, Any]) -> EnrichmentResult:
        started = time.monotonic()
        within_budget = lambda: time.monotonic() - started < self.budget_seconds  # noqa: E731
        result = EnrichmentResult(company_id=row["id"], patch={})
        log = result.log
        edited = set(row.get("edited_fields") or [])
        metadata = dict(row.get("metadata") or {})
        metadata_patch: dict[str, Any] = {}
        founded_facts: list[FoundedFact | None] = []
        company = CompanyProfile(
            name=row["name"],
            city=row.get("city"),
            state=row.get("state"),
            country=row.get("country"),
            description=row.get("description"),
        )
        source_name = (row.get("source_name") or "").lower()
        source_url = row.get("source_url") or ""
        kind = row.get("entity_kind") or "startup"
        original_website = canonical_url(row.get("website"))
        website = original_website
        discovery_source = row.get("website_discovery_source")
        yc_jobs: tuple[int, str | None] | None = None

        # 1. Structured source profile (YC company page).
        if "ycombinator.com/companies/" in source_url:
            facts = self.discovery.yc_profile(source_url)
            if facts:
                if facts.founded_year:
                    founded_facts.append(FoundedFact(facts.founded_year, "yc_profile"))
                if facts.jobs_count is not None:
                    yc_jobs = (facts.jobs_count, facts.jobs_url)
                    metadata_patch["yc_jobs_count"] = facts.jobs_count
                metadata_patch.update(facts.extra)
                if not website and facts.website:
                    website = canonical_url(facts.website)
                    discovery_source = "yc_profile"
                    log.append("website from YC profile")

        # 2. Check the known website.
        site: VerifiedSite | None = None
        status: str | None = None
        if website:
            page, error = self.discovery.load(website)
            if page is None:
                status = "unverified" if error and "robots" in error else "unreachable"
                log.append(f"website {status}: {error}")
            else:
                score = score_page(company, page.base_url, page)
                status = "verified" if score >= 2 else "unverified"
                site = VerifiedSite(page.base_url, page, score)

        # 3. Discover a website when none is known (or the known one is dead).
        wikidata_checked = False
        if "website" not in edited and (website is None or status == "unreachable") and within_budget():
            found: VerifiedSite | None = None
            how = None
            article_url = metadata.get("article_url") or (
                source_url if source_url.startswith("http") and "sec.gov" not in source_url and "ycombinator.com" not in source_url else ""
            )
            if article_url:
                found = self.discovery.verify_best(
                    company, self.discovery.article_candidates(company, article_url), threshold=3
                )
                how = "news_article" if found else None
            if not found and within_budget() and kind not in SKIP_GUESSING_KINDS:
                # A guessed domain can belong to a namesake; when we know what the company does,
                # the site must also mention it (or its location).
                found = self.discovery.verify_best(
                    company,
                    self.discovery.guess_domains(company, row.get("country"))[:6],
                    threshold=4,
                    require_context=bool(company.description_keywords()),
                )
                how = "domain_guess" if found else None
            if not found and within_budget() and kind not in SKIP_GUESSING_KINDS:
                wikidata_checked = True
                facts = self.discovery.wikidata(company)
                if facts:
                    metadata_patch.update(facts.extra)
                    if facts.founded_year:
                        founded_facts.append(FoundedFact(facts.founded_year, "wikidata", facts.founded_on))
                    if facts.website:
                        found = self.discovery.verify(company, facts.website, threshold=3)
                        how = "wikidata" if found else None
            if not found and within_budget():
                found = self.discovery.verify_best(company, self.discovery.brave_search(company), threshold=3)
                how = "search_api" if found else None
            if found:
                if website and status == "unreachable":
                    metadata_patch["previous_website"] = website
                website, site, status, discovery_source = found.url, found, "verified", how
                result.website_found = True
                log.append(f"website found via {how}: {found.url} (score {found.score})")
            elif website is None:
                status = "not_found"
                log.append("no website found")

        # 4. Careers page and founding date from the website itself.
        careers: CareersResult | None = None
        if site is not None and within_budget():
            careers = self.careers.detect(site.page)
            founded_facts.extend([from_structured_data(site.page), from_text(site.page)])
            if (best(*founded_facts) is None or best(*founded_facts).rank < 40) and within_budget():
                about = about_page_url(site.page)
                if about:
                    page, _ = self.discovery.load(about)
                    if page is not None:
                        founded_facts.extend([from_structured_data(page), from_text(page)])

        # Wikidata often knows the founding date of notable companies.
        current_rank = founded_rank(row.get("founded_source") or "legacy") if row.get("founded_year") else 0
        best_so_far = best(*founded_facts)
        if (
            not wikidata_checked
            and kind not in SKIP_GUESSING_KINDS
            and max(current_rank, best_so_far.rank if best_so_far else 0) < 60
            and within_budget()
        ):
            facts = self.discovery.wikidata(company)
            if facts and facts.founded_year and (
                not facts.website or not website or domain_from_url(facts.website) == domain_from_url(website)
            ):
                founded_facts.append(FoundedFact(facts.founded_year, "wikidata", facts.founded_on))
                metadata_patch.update(facts.extra)

        if site is not None and within_budget():
            best_so_far = best(*founded_facts)
            if max(current_rank, best_so_far.rank if best_so_far else 0) < 40:
                registered = domain_registration(self.client, site.url)
                if registered:
                    result.patch["domain_registered_on"] = registered
                    founded_facts.append(FoundedFact(int(registered[:4]), "domain_registration", registered))

        # YC's own job board counts as a careers page when the website has none.
        if yc_jobs and yc_jobs[0] > 0:
            if careers is None or not careers.has_careers_page:
                careers = CareersResult(True, yc_jobs[1], "yc", yc_jobs[0])
            elif careers.open_jobs is None:
                careers.open_jobs = yc_jobs[0]

        # 5. Build the patch.
        now = utc_now()
        patch = result.patch
        patch.update({"enriched_at": now, "enrichment_error": None})
        if "website" not in edited:
            if website != original_website:
                patch["website"] = website
                patch["domain"] = domain_from_url(website)
                patch["website_discovery_source"] = discovery_source
            if status:
                patch["website_status"] = status
            if status == "verified":
                patch["website_verified_at"] = now
        if careers is not None and not ({"has_careers_page", "careers_url", "open_jobs_count"} & edited):
            patch.update({
                "has_careers_page": careers.has_careers_page,
                "careers_url": careers.careers_url,
                "careers_provider": careers.provider,
                "open_jobs_count": careers.open_jobs,
                "careers_checked_at": now,
            })
            if careers.open_jobs is not None:
                patch["is_hiring"] = careers.open_jobs > 0
            result.careers_found = careers.has_careers_page
            log.append(
                f"careers: {careers.provider} {careers.careers_url} jobs={careers.open_jobs}"
                if careers.has_careers_page else "careers: none found"
            )
        if "founded_year" not in edited:
            candidate = best(*founded_facts)
            if candidate and candidate.rank > current_rank:
                patch.update({"founded_year": candidate.year, "founded_on": candidate.on, "founded_source": candidate.source})
                result.founded_found = True
                log.append(f"founded {candidate.year} ({candidate.source})")
        if metadata_patch:
            patch["metadata"] = {**metadata, **metadata_patch}
        return result
