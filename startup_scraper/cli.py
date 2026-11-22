from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .enrichment import DEFAULT_USER_AGENT, Enricher
from .pipeline import ENRICH_TARGETS, collect, run_enrichment, select_enrichment_ids
from .supabase import SupabaseStore
from .stage_filter import EARLY_STAGE_TYPES, filter_by_stage_types, normalize_requested
from .sources.early_stage import SUPPORTED as EARLY_STAGE_SOURCES


def load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Collect funded startup data into Supabase")
    all_sources = ("sec", "rss", "yc", *EARLY_STAGE_SOURCES)
    result.add_argument(
        "--sources",
        default=",".join(all_sources),
        help="Comma-separated: " + ",".join(all_sources),
    )
    result.add_argument("--sec-quarters", type=int, default=1, help="Number of recent SEC bulk quarters")
    result.add_argument("--include-funds", action="store_true", help="Include pooled investment funds from SEC data")
    result.add_argument("--limit", type=int, help="Maximum records per source (useful for tests)")
    result.add_argument(
        "--funding-types",
        default="",
        help="Only save explicit early-stage matches. Comma-separated: " + ",".join(EARLY_STAGE_TYPES),
    )
    result.add_argument("--dry-run", action="store_true", help="Collect and print samples without writing")
    result.add_argument("--json-output", help="Also save collected rows to a local JSON file")
    enrich = result.add_argument_group("enrichment (website, careers page, founding date)")
    enrich.add_argument("--enrich", type=int, default=0, metavar="N", help="After collecting, enrich up to N companies")
    enrich.add_argument("--enrich-only", action="store_true", help="Skip collection and only run enrichment")
    enrich.add_argument("--enrich-target", default="missing_website", choices=sorted(ENRICH_TARGETS), help="Which companies to enrich")
    enrich.add_argument("--startups-only", action="store_true", help="Skip investment vehicles, real estate, and other SPVs")
    enrich.add_argument("--workers", type=int, default=6, help="Concurrent enrichment workers")
    return result


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parser().parse_args(argv)
    selected = {value.strip().lower() for value in args.sources.split(",") if value.strip()}
    invalid = selected - {"sec", "rss", "yc", *EARLY_STAGE_SOURCES}
    if invalid:
        raise SystemExit(f"Unknown sources: {', '.join(sorted(invalid))}")
    try:
        funding_types = normalize_requested(args.funding_types.split(","))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    store = None
    if not args.dry_run:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
        if not url or not key:
            print(
                "error: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY), "
                "or run with --dry-run",
                file=sys.stderr,
            )
            return 2
        store = SupabaseStore(url, key)
        try:
            store.check_schema()
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    if not args.enrich_only:
        companies, rounds = collect(
            selected,
            sec_user_agent=os.getenv("SEC_USER_AGENT"),
            sec_quarters=args.sec_quarters,
            limit=args.limit,
            include_funds=args.include_funds,
            directory_user_agent=os.getenv("ENRICH_USER_AGENT") or DEFAULT_USER_AGENT,
        )
        companies, rounds = filter_by_stage_types(companies, rounds, funding_types)
        if funding_types:
            print(
                f"Matched {len(companies)} companies to selected funding/stage types: "
                f"{', '.join(sorted(funding_types))}"
            )
        if args.json_output:
            payload = {"companies": [item.row() for item in companies], "funding_rounds": [item.row() for item in rounds]}
            Path(args.json_output).write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
            print(f"Wrote {args.json_output}")
        if args.dry_run:
            for item in companies[:3]:
                print(json.dumps(item.row(), ensure_ascii=False, default=str))
            return 0
        assert store is not None
        company_count, round_count = store.save(companies, rounds)
        print(f"Saved/upserted {company_count} companies and {round_count} funding rounds")

    enrich_count = args.enrich or (200 if args.enrich_only else 0)
    if enrich_count and store is not None:
        ids = select_enrichment_ids(store, args.enrich_target, enrich_count, only_startups=args.startups_only)
        print(f"Enriching {len(ids)} companies ({ENRICH_TARGETS[args.enrich_target].lower()})…")
        enricher = Enricher(os.getenv("ENRICH_USER_AGENT") or DEFAULT_USER_AGENT)

        def report(result) -> None:
            status = "error" if result.error else "; ".join(result.log[-3:]) or "no changes"
            print(f"  {result.company_id}: {status}")

        counters = run_enrichment(store, ids, enricher=enricher, workers=args.workers, on_result=report)
        print(
            f"Enriched {counters['processed']}: {counters['websites_found']} websites found, "
            f"{counters['careers_found']} careers pages, {counters['founded_found']} founding dates, "
            f"{counters['contacts_found']} with new links/contact email, "
            f"{counters['errors']} errors"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
