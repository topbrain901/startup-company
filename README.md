# Funding Radar

Find recently funded startups, their official websites, careers pages, and founding dates, and track which ones you have looked at.

```
startup_scraper/   Python collector + enrichment (no third-party dependencies, no API keys)
backend/           FastAPI API: auth, roles, search/filters, notes, viewed status, admin + scrape jobs
startup-dashboard/ Next.js (vinext) dashboard: Companies page; Scraper and Users pages for admins
supabase/          SQL migrations (run in order in the Supabase SQL editor)
tests/             unittest suites for parsing, enrichment, and the API
```

The browser never talks to Supabase data tables. It signs in with Supabase Auth, and every data request goes
`dashboard → /api/backend proxy (adds the session) → FastAPI → Supabase (service-role key)`.

## Setup

1. **Database**: in the Supabase SQL editor run, in order:
   `supabase/migrations/001_startup_funding.sql` (already applied if you have data),
   `002_…` (optional), and **`003_roles_notes_views_enrichment.sql`**. 003 is safe to re-run. It also cleans existing data:
   it normalises countries (`USA; Remote` → United States + remote flag), title-cases SEC locations, replaces the
   wrong YC founding years with batch-year estimates, classifies company types, and builds funding summaries.
2. **Environment**: copy `.env.example` to `.env` at the repo root (used by the collector and the API; the API also
   reads `backend/.env`, which takes priority) and set the
   Supabase URL, service-role key, `SEC_USER_AGENT`, and `ADMIN_EMAILS` (your login email, so you become admin).
3. **API**:
   ```powershell
   pip install -r backend/requirements.txt
   uvicorn backend.app.main:app --port 8000
   ```
   Interactive docs: http://127.0.0.1:8000/docs. Run a single worker process (background jobs live in-process).
4. **Dashboard**: in `startup-dashboard/.env` set `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `FASTAPI_URL`
   (defaults to `http://127.0.0.1:8000` in development), then `npm run dev`.
5. Sign up or sign in. Emails listed in `ADMIN_EMAILS` become administrators; promote others on the **Users** page.

## Roles

| | User | Admin |
|---|---|---|
| Browse and filter companies, export CSV | ✓ | ✓ |
| Private note per company | ✓ | ✓ |
| Viewed / not viewed (auto-marked when a company is opened, toggle in the table) | ✓ | ✓ |
| Add, edit, and delete companies and funding rounds | | ✓ |
| Start / cancel scrapes and enrichment, see run history | | ✓ |
| Change user roles | | ✓ |

Notes and viewed status are per person. Fields an admin edits are locked against future scrapes and enrichment
(unlock them from the company drawer). Deleted companies are remembered so a re-scrape does not bring them back
(restore them on the Scraper page).

## Filters

Free-text search, plus: country, state/region, city/place text, remote; has website; careers page
(yes / no / not checked), job board provider (Greenhouse, Lever, Ashby, YC, company site…), hiring, minimum open
jobs; round type, last funded within, latest round and total raised amounts; industry, company type
(startup / fund / real estate / other), founded-year range, founding date known, team size, stage, status, YC batch,
data source, recently added; viewed and has-note. Quick chips cover the common ones, and every filter is kept in
the URL so views can be bookmarked.

## Enrichment without API keys

Search engines block automated queries (Google, Bing, and DuckDuckGo serve bot challenges; Brave's robots.txt
disallows `/search`), so the enricher does not scrape them. It finds websites from sources that name the company,
and only accepts a candidate after **fetching the homepage and verifying it** (name in the title/brand, domain match,
location or description words, parked-domain detection):

1. YC company profile (website, real founding year, YC job postings)
2. Links in the funding article the company came from
3. Name-based domain guesses (`huxleymed.com`, `acme.ai`, `getacme.com`, country TLDs…) checked via DNS
4. Wikidata (official website + inception date for notable companies)
5. Optional: `BRAVE_SEARCH_API_KEY` (Brave's official API; paid, with a small monthly credit) as a last resort

On each website it then looks for a **careers/jobs page** (nav links, common paths such as `/careers`, careers
subdomains, and embedded job boards), and reads **open-job counts** from the public Greenhouse, Lever, Ashby,
Workable, Recruitee, and SmartRecruiters APIs. **Founding dates** come, best first, from SEC filings, YC profiles,
Wikidata, the site's structured data or "founded in …" text, then estimates (YC batch, domain registration via
RDAP, copyright range). The UI marks estimates with `~`.

On a sample of real records this found sites for 8 of 12 SEC-filing startups and 7 of 8 news-sourced companies.
SEC filers that are funds or SPVs mostly have no website, and are skipped when "Startups only" is on.
The enricher identifies itself as `FundingRadarBot`, honours robots.txt, and rate-limits per host.

## CLI

```powershell
python -m startup_scraper --sources sec,rss,yc --sec-quarters 1             # collect and save
python -m startup_scraper --sources rss --limit 10 --dry-run                 # preview only
python -m startup_scraper --enrich-only --enrich 300 --enrich-target missing_website --startups-only
```

Enrichment targets: `never`, `missing_website`, `missing_founded`, `careers_unchecked`, `stale`, `all`.
Companies that were tried recently without success are skipped for 14 days, so repeated runs make progress.

## Tests

```powershell
python -m unittest discover -s tests
```

## Data notes

- A Form D is a notice of an exempt offering, not proof the issuer is a tech startup; use the company-type filter.
- Form D `amount_usd` is the issuer-reported total amount sold, which may be cumulative on amendments.
- News amounts are parsed from headlines and summaries, and are flagged for verification in metadata.
- The collector stores public company facts only. It does not collect personal emails, bypass logins, or fetch pages
  disallowed by robots.txt.
