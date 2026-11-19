# Funding Radar API (FastAPI)

Verifies Supabase access tokens, reads each user's role from `public.profiles`, and enforces admin/user
permissions on every endpoint. All database access uses the service-role key, server-side.

## Run locally

```powershell
# from the repository root
uvicorn backend.app.main:app --reload --port 8000

# or from inside backend/
uvicorn app.main:app --reload --port 8000
```

Install dependencies first with `pip install -r requirements.txt` (inside `backend/`). Settings come from the
repository-root `.env` and `backend/.env` (the latter wins). If you use a port other than 8000, set
`FASTAPI_URL=http://127.0.0.1:<port>` in `startup-dashboard/.env`.
Apply `supabase/migrations/003_roles_notes_views_enrichment.sql` first. Set `ADMIN_EMAILS` to your login email,
or promote a user in SQL:

```sql
update public.profiles set role = 'admin' where email = 'you@example.com';
```

OpenAPI docs: `http://127.0.0.1:8000/docs`.

## Endpoints

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/me` | any | Current user and role |
| GET | `/companies` | any | Search with filters, sort, pagination (see `/docs` for every filter) |
| GET | `/companies/export` | any | CSV of the current filter (≤ 5,000 rows) |
| GET | `/companies/facets` | any | Filter values with counts |
| GET | `/companies/{id}` | any | Company + funding rounds + your note and viewed state |
| PUT | `/companies/{id}/note` | any | Save your private note (empty deletes it) |
| PUT | `/companies/{id}/view` | any | Mark viewed / not viewed |
| POST | `/companies/views` | any | Bulk viewed / not viewed |
| POST, PATCH, DELETE | `/admin/companies…` | admin | Create, edit (fields get locked), delete (remembered), bulk delete, unlock |
| POST | `/admin/companies/{id}/enrich` | admin | Re-run website / careers / founding-date discovery now |
| POST, PATCH, DELETE | `/admin/funding-rounds…` | admin | Manage funding rounds |
| POST | `/admin/jobs/collect`, `/admin/jobs/enrich` | admin | Start a background scrape or enrichment job |
| GET | `/admin/jobs`, `/admin/jobs/active`, `/admin/jobs/{id}` | admin | History, live progress, log |
| POST | `/admin/jobs/{id}/cancel` | admin | Cancel the running job |
| GET | `/admin/stats` | admin | Data coverage |
| GET, PATCH | `/admin/users…` | admin | List users, change roles |
| GET, POST | `/admin/deleted-companies…` | admin | List and restore deleted companies |

Jobs run one at a time in a background thread and persist progress to `public.scrape_runs`. Run a single uvicorn
worker. Runs interrupted by a restart are marked failed on startup.

`POST /admin/jobs/collect` accepts an optional `funding_types` array containing `pre-seed`, `bootstrapped`,
`pre-funding`, `ideation`, and/or `self-funded`. An empty array means all stages. Matching is conservative and
uses explicit wording in the source company/round data.

Supported `sources` values are `sec`, `rss`, `yc`, `producthunt`, `betalist`, `antler`, `ef`, `techstars`, and
`wellfound`. The directory collectors use public pages only and honour robots.txt and host crawl delays.

## Deploy

The Dockerfile and `render.yaml` deploy the API on any Python container host. Set `FASTAPI_URL` on the dashboard
to the public API URL afterwards.
