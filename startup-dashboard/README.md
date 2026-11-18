# Funding Radar dashboard

Next.js App Router (vinext) dashboard for the Funding Radar API.

- **Companies** (everyone): search, quick filters, a full filter panel (location, website, careers page, job board,
  hiring, funding round/amount/date, industry, company type, founded year, team size, viewed, notes), sortable table
  with a viewed checkbox, CSV export, and a detail drawer with your private note.
- **Scraper** and **Users** (admins only): start or cancel scrape and enrichment jobs, watch progress and logs,
  see data coverage, restore deleted companies, and manage roles.
- **Theme**: Auto / Light / Dark switch in the sidebar (and on the sign-in page). Auto follows the device setting;
  the choice is saved per browser. Colors are CSS variables in `app/globals.css` (light on `:root`, dark on
  `:root[data-theme="dark"]`); `lib/theme.ts` applies the theme before first paint.

Sign-in uses Supabase email/password with HTTP-only session cookies (`app/api/auth`). Every data call goes through
`app/api/backend/[...path]`, which forwards the session token to FastAPI. The browser never holds a database key.

## Local development

Start the API first (see `../backend/README.md`), then:

```powershell
npm install
npm run dev
```

## Environment

- `SUPABASE_URL`, `SUPABASE_ANON_KEY`: sign-in
- `FASTAPI_URL`: the API base URL (defaults to `http://127.0.0.1:8000` outside production)

The dashboard no longer needs `SUPABASE_SERVICE_ROLE_KEY`; remove it from this app's environment.
