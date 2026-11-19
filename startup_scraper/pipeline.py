"""Collection and enrichment steps shared by the CLI and the FastAPI job runner."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

from .enrichment import Enricher, EnrichmentResult
from .http import HttpClient
from .models import Company, FundingRound
from .sources import early_stage, rss, sec_form_d, yc
from .supabase import SupabaseStore, in_list


Log = Callable[[str], None]

ENRICH_TARGETS = {
    "never": "Never enriched",
    "missing_website": "Missing website",
    "missing_founded": "Missing or estimated founding date",
    "careers_unchecked": "Website known, careers not checked",
    "stale": "Enriched more than 30 days ago",
    "all": "All companies",
}
ESTIMATED_FOUNDED = "(yc_batch_estimate,domain_registration,website_copyright,legacy)"
PAGE = 1000  # Supabase caps a single REST response at 1000 rows by default.


def collect(
    sources: set[str],
    *,
    sec_user_agent: str | None,
    sec_quarters: int = 1,
    limit: int | None = None,
    include_funds: bool = False,
    directory_user_agent: str = "Mozilla/5.0 (compatible; FundingRadarBot/1.0)",
    log: Log = print,
) -> tuple[list[Company], list[FundingRound]]:
    companies: list[Company] = []
    rounds: list[FundingRound] = []
    if "sec" in sources:
        if not sec_user_agent:
            log("SEC skipped: set SEC_USER_AGENT with your name and email")
        else:
            log(f"Collecting SEC Form D data ({sec_quarters} quarter(s))…")
            for company, funding in sec_form_d.collect(
                HttpClient(user_agent=sec_user_agent), quarter_count=sec_quarters, limit=limit, include_funds=include_funds
            ):
                companies.append(company)
                rounds.append(funding)
    if "rss" in sources:
        log("Collecting funding-news feeds…")
        for company, funding in rss.collect(HttpClient(timeout=20), limit=limit):
            companies.append(company)
            rounds.append(funding)
    if "yc" in sources:
        log("Collecting Y Combinator directory…")
        companies.extend(yc.collect(HttpClient(timeout=60), limit=limit))
    labels = {
        "producthunt": "Product Hunt launches",
        "betalist": "BetaList early-access startups",
        "antler": "Antler portfolio",
        "ef": "Entrepreneur First portfolio",
        "techstars": "Techstars portfolio",
        "wellfound": "Wellfound startup directory",
    }
    for source in early_stage.SUPPORTED:
        if source in sources:
            log(f"Collecting {labels[source]}…")
            companies.extend(
                early_stage.collect(source, user_agent=directory_user_agent, limit=limit, log=log)
            )
    # Collapse repeat sightings inside the same run.
    companies = list({item.source_key: item for item in companies}.values())
    rounds = list({item.source_key: item for item in rounds}.values())
    log(f"Collected {len(companies)} company rows and {len(rounds)} funding rows")
    return companies, rounds


def select_enrichment_ids(
    store: SupabaseStore,
    target: str,
    limit: int,
    *,
    only_startups: bool = False,
    sources: list[str] | None = None,
    retry_after_days: int = 14,
) -> list[str]:
    """IDs to enrich, least-recently-enriched first. Companies that were just tried without
    success are skipped for `retry_after_days` so repeated runs make progress."""
    if target not in ENRICH_TARGETS:
        raise ValueError(f"Unknown enrichment target: {target}")
    retry_cutoff = (date.today() - timedelta(days=retry_after_days)).isoformat()
    stale_cutoff = (date.today() - timedelta(days=30)).isoformat()
    conditions = {
        "never": ["enriched_at.is.null"],
        "missing_website": ["website.is.null", f"or(enriched_at.is.null,enriched_at.lt.{retry_cutoff})"],
        "missing_founded": [
            f"or(founded_year.is.null,founded_source.in.{ESTIMATED_FOUNDED})",
            f"or(enriched_at.is.null,enriched_at.lt.{retry_cutoff})",
        ],
        "careers_unchecked": ["website.not.is.null", "careers_checked_at.is.null"],
        "stale": [f"enriched_at.lt.{stale_cutoff}"],
        "all": [],
    }[target]
    if only_startups:
        conditions.append("entity_kind.eq.startup")
    if sources:
        conditions.append(f"source_name.in.{in_list(sources)}")
    query = "select=id&order=enriched_at.asc.nullsfirst,last_seen_at.desc"
    if conditions:
        query += "&and=" + quote(f"({','.join(conditions)})", safe='(),."')
    ids: list[str] = []
    while len(ids) < limit:
        page_size = min(PAGE, limit - len(ids))
        rows = store.select("startup_companies", f"{query}&limit={page_size}&offset={len(ids)}")
        ids.extend(row["id"] for row in rows)
        if len(rows) < page_size:
            break
    return ids


def _rows(store: SupabaseStore, ids: list[str]) -> Iterator[dict[str, Any]]:
    for index in range(0, len(ids), 100):
        yield from store.enrichment_rows(ids[index : index + 100])


def run_enrichment(
    store: SupabaseStore,
    ids: list[str],
    *,
    enricher: Enricher,
    workers: int = 6,
    should_stop: Callable[[], bool] = lambda: False,
    on_result: Callable[[EnrichmentResult], None] | None = None,
) -> Counter:
    """Enrich companies concurrently and persist each result as soon as it is ready."""
    counters: Counter = Counter()

    def process(row: dict[str, Any]) -> EnrichmentResult:
        result = enricher.enrich(row)
        try:
            store.save_enrichment(row["id"], result.patch)
        except Exception as exc:  # noqa: BLE001 - report and continue
            result.error = f"save failed: {exc}"[:500]
        return result

    rows = _rows(store, ids)
    pending: set[Future[EnrichmentResult]] = set()
    exhausted = False
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        while True:
            while not exhausted and not should_stop() and len(pending) < max(1, workers) * 2:
                row = next(rows, None)
                if row is None:
                    exhausted = True
                    break
                pending.add(pool.submit(process, row))
            if not pending:
                break
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                result = future.result()
                counters["processed"] += 1
                counters["websites_found"] += int(result.website_found)
                counters["careers_found"] += int(result.careers_found)
                counters["founded_found"] += int(result.founded_found)
                counters["errors"] += int(result.error is not None)
                if on_result:
                    on_result(result)
    return counters
