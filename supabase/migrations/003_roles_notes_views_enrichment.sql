-- Funding Radar: roles, per-user notes and view state, enrichment fields, funding summaries,
-- scrape-job tracking, and the search/facet functions used by the FastAPI backend.
--
-- Run in the Supabase SQL editor after 001 (and optionally 002). Safe to re-run.
-- All application access goes through the FastAPI backend with the service-role key;
-- browsers never query these tables directly.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------------
-- 1. Company columns
-- ---------------------------------------------------------------------------
alter table public.startup_companies
  add column if not exists is_remote boolean,
  add column if not exists entity_kind text,
  add column if not exists founded_on date,
  add column if not exists founded_source text,
  add column if not exists website_status text,
  add column if not exists website_verified_at timestamptz,
  add column if not exists website_discovery_source text,
  add column if not exists domain_registered_on date,
  add column if not exists careers_url text,
  add column if not exists has_careers_page boolean,
  add column if not exists careers_provider text,
  add column if not exists open_jobs_count integer,
  add column if not exists careers_checked_at timestamptz,
  add column if not exists enriched_at timestamptz,
  add column if not exists enrichment_error text,
  add column if not exists edited_fields text[] not null default '{}',
  add column if not exists latest_round_type text,
  add column if not exists latest_round_on date,
  add column if not exists latest_amount_usd numeric,
  add column if not exists total_funding_usd numeric,
  add column if not exists round_count integer not null default 0,
  add column if not exists round_types text[] not null default '{}';

-- ---------------------------------------------------------------------------
-- 2. Helper functions
-- ---------------------------------------------------------------------------
-- Higher rank = better evidence for the founding date (mirrors startup_scraper/founding.py).
create or replace function public.founded_source_rank(src text)
returns integer language sql immutable as $$
  select case
    when src is null then 0
    when src = 'manual' then 100
    when src = 'sec_form_d' then 80
    when src = 'yc_profile' then 70
    when src = 'wikidata' then 60
    when src = 'website_structured_data' then 50
    when src = 'website_text' then 40
    when src = 'yc_batch_estimate' then 25
    when src = 'domain_registration' then 20
    when src = 'website_copyright' then 15
    else 30
  end;
$$;

create or replace function public.jsonb_text_array(j jsonb)
returns text[] language sql immutable as $$
  select case
    when j is null or jsonb_typeof(j) <> 'array' or jsonb_array_length(j) = 0 then null
    else array(select jsonb_array_elements_text(j))
  end;
$$;

create or replace function public.normalize_country(value text)
returns text language sql immutable as $$
  with cleaned as (
    select nullif(btrim(regexp_replace(split_part(coalesce(value, ''), ';', 1), '\s*\(.*?\)\s*', ' ', 'g'), ' ,'), '') as v
  )
  select case
    when v is null or lower(v) = 'remote' then null
    when lower(regexp_replace(v, '[^a-zA-Z ]', '', 'g')) in ('usa', 'us', 'united states', 'united states of america', 'america') then 'United States'
    when lower(regexp_replace(v, '[^a-zA-Z ]', '', 'g')) in ('uk', 'great britain', 'england', 'scotland', 'wales', 'northern ireland') then 'United Kingdom'
    when lower(regexp_replace(v, '[^a-zA-Z ]', '', 'g')) in ('uae') then 'United Arab Emirates'
    when lower(v) in ('korea', 'republic of korea') then 'South Korea'
    when lower(v) in ('the netherlands', 'holland') then 'Netherlands'
    when v = upper(v) and length(v) > 3 then initcap(lower(v))
    else v
  end
  from cleaned;
$$;

-- ---------------------------------------------------------------------------
-- 3. One-time data cleanup (idempotent)
-- ---------------------------------------------------------------------------
-- Remote flag and canonical country names ("USA; Remote" -> United States + remote).
update public.startup_companies
set is_remote = true
where is_remote is null and (country ilike '%remote%' or location ilike '%remote%');

update public.startup_companies
set country = public.normalize_country(country)
where country is not null and country is distinct from public.normalize_country(country);

-- SEC filings are ALL CAPS ("ATLANTA", "GEORGIA").
update public.startup_companies
set city = initcap(lower(city))
where source_name = 'SEC EDGAR Form D' and city is not null and city = upper(city);

update public.startup_companies
set state = initcap(lower(state))
where source_name = 'SEC EDGAR Form D' and state is not null and state = upper(state);

update public.startup_companies
set location = concat_ws(', ', city, coalesce(state, country))
where source_name = 'SEC EDGAR Form D' and location is not null and location = upper(location);

-- YC "San Francisco, CA, USA": fill state from the location string.
with us_states(code, name) as (values
  ('AL','Alabama'),('AK','Alaska'),('AZ','Arizona'),('AR','Arkansas'),('CA','California'),('CO','Colorado'),
  ('CT','Connecticut'),('DE','Delaware'),('DC','District of Columbia'),('FL','Florida'),('GA','Georgia'),
  ('HI','Hawaii'),('ID','Idaho'),('IL','Illinois'),('IN','Indiana'),('IA','Iowa'),('KS','Kansas'),
  ('KY','Kentucky'),('LA','Louisiana'),('ME','Maine'),('MD','Maryland'),('MA','Massachusetts'),
  ('MI','Michigan'),('MN','Minnesota'),('MS','Mississippi'),('MO','Missouri'),('MT','Montana'),
  ('NE','Nebraska'),('NV','Nevada'),('NH','New Hampshire'),('NJ','New Jersey'),('NM','New Mexico'),
  ('NY','New York'),('NC','North Carolina'),('ND','North Dakota'),('OH','Ohio'),('OK','Oklahoma'),
  ('OR','Oregon'),('PA','Pennsylvania'),('RI','Rhode Island'),('SC','South Carolina'),('SD','South Dakota'),
  ('TN','Tennessee'),('TX','Texas'),('UT','Utah'),('VT','Vermont'),('VA','Virginia'),('WA','Washington'),
  ('WV','West Virginia'),('WI','Wisconsin'),('WY','Wyoming'),('PR','Puerto Rico')
)
update public.startup_companies c
set state = s.name
from us_states s
where c.source_name = 'Y Combinator directory'
  and c.state is null
  and c.country = 'United States'
  and upper(btrim(split_part(split_part(c.location, ';', 1), ',', 2))) = s.code;

-- yc-oss "launched_at" was stored as the founding year, but it is the YC profile publish date
-- (2012 for Stripe). Use the batch year as an estimate until enrichment reads the profile.
update public.startup_companies
set founded_year = (
      case when m[2] ~ '^\d{2}$' then 2000 + m[2]::int else m[2]::int end
    ),
    founded_source = 'yc_batch_estimate'
from (
  select id as cid, regexp_match(accelerator_batch, '(winter|summer|spring|fall|autumn|[wsfx])\s*''?(\d{4}|\d{2})', 'i') as m
  from public.startup_companies
  where source_name = 'Y Combinator directory'
) parsed
where startup_companies.id = parsed.cid
  and parsed.m is not null
  and (founded_source is null or founded_source = 'yc_batch_estimate');

update public.startup_companies
set founded_year = null
where source_name = 'Y Combinator directory' and founded_source is null;

update public.startup_companies
set founded_source = 'legacy'
where founded_year is not null and founded_source is null;

-- Rough company type for filtering (mirrors startup_scraper.util.classify_entity).
update public.startup_companies
set entity_kind = case
  when source_name ilike '%y combinator%' then 'startup'
  when source_name <> 'SEC EDGAR Form D' then 'startup'
  when lower(coalesce(industry, '')) in ('pooled investment fund', 'investing', 'other banking and financial services',
       'commercial banking', 'investment banking', 'insurance', 'health insurance')
    or name ~* '\m(fund|funds|feeder|offshore|onshore|master|co-?invest(ment)?|spv|l\.?p\.?|lp|partners|investors|investments?|opportunit(y|ies)|portfolio|income|yield|trust|reit)\M'
    or name ~* '\mseries\s+[a-z0-9]+\s+of\M'
    or name ~* '\mcapital\s+(partners|fund|holdings)\M'
    or name ~* '\macquisition\s+corp'
    or name ~* '\m(holdings?|ventures?)\s+([ivx]+|\d+)\M'
    then 'investment_vehicle'
  when lower(coalesce(industry, '')) in ('other real estate', 'commercial', 'residential', 'reits and finance',
       'construction', 'lodging and conventions')
    or name ~* '\m(apartments?|properties|property|realty|real\s+estate|residences?|lofts?|villas?|commons|plaza|tower|storage|hotel|hospitality|multifamily|housing|homes|land|timberland|dst)\M'
    then 'real_estate'
  when lower(coalesce(industry, '')) in ('restaurants', 'retailing', 'oil and gas', 'coal mining', 'electric utilities',
       'agriculture', 'airlines and airports', 'tourism and travel services', 'other travel', 'travel')
    then 'other'
  else 'startup'
end
where entity_kind is null;

-- ---------------------------------------------------------------------------
-- 4. Funding summary maintained on the company row (fast filtering/sorting)
-- ---------------------------------------------------------------------------
create or replace function public.refresh_company_funding(p_company uuid)
returns void language sql as $$
  update public.startup_companies c
  set round_count = s.cnt,
      total_funding_usd = s.total,
      latest_round_on = s.latest_on,
      latest_round_type = s.latest_type,
      latest_amount_usd = s.latest_amount,
      round_types = s.types
  from (
    select
      count(*)::int as cnt,
      sum(amount_usd) as total,
      (array_agg(announced_on order by announced_on desc nulls last, created_at desc))[1] as latest_on,
      (array_agg(round_type order by announced_on desc nulls last, created_at desc))[1] as latest_type,
      (array_agg(amount_usd order by announced_on desc nulls last, created_at desc))[1] as latest_amount,
      coalesce(array_agg(distinct round_type) filter (where round_type is not null), '{}') as types
    from public.funding_rounds
    where company_id = p_company
  ) s
  where c.id = p_company;
$$;

create or replace function public.funding_rounds_after_change()
returns trigger language plpgsql as $$
begin
  if tg_op in ('INSERT', 'UPDATE') then
    perform public.refresh_company_funding(new.company_id);
  end if;
  if tg_op = 'DELETE' or (tg_op = 'UPDATE' and old.company_id is distinct from new.company_id) then
    perform public.refresh_company_funding(old.company_id);
  end if;
  return null;
end;
$$;

drop trigger if exists funding_rounds_refresh_company on public.funding_rounds;
create trigger funding_rounds_refresh_company
after insert or update or delete on public.funding_rounds
for each row execute function public.funding_rounds_after_change();

-- Backfill in one pass.
update public.startup_companies c
set round_count = s.cnt,
    total_funding_usd = s.total,
    latest_round_on = s.latest_on,
    latest_round_type = s.latest_type,
    latest_amount_usd = s.latest_amount,
    round_types = s.types
from (
  select
    company_id,
    count(*)::int as cnt,
    sum(amount_usd) as total,
    (array_agg(announced_on order by announced_on desc nulls last, created_at desc))[1] as latest_on,
    (array_agg(round_type order by announced_on desc nulls last, created_at desc))[1] as latest_type,
    (array_agg(amount_usd order by announced_on desc nulls last, created_at desc))[1] as latest_amount,
    coalesce(array_agg(distinct round_type) filter (where round_type is not null), '{}') as types
  from public.funding_rounds
  group by company_id
) s
where c.id = s.company_id;

-- ---------------------------------------------------------------------------
-- 5. Protect curated data from re-scrapes
-- ---------------------------------------------------------------------------
-- The collector sends "X-Data-Origin: scraper"; enrichment sends "enricher". A source
-- re-import must never blank out what enrichment found or what an administrator edited.
create or replace function public.protect_curated_company_fields()
returns trigger language plpgsql as $$
declare
  origin text;
  keep jsonb;
begin
  begin
    origin := coalesce(nullif(current_setting('request.headers', true), '')::json ->> 'x-data-origin', '');
  exception when others then
    origin := '';
  end;
  if origin not in ('scraper', 'enricher') then
    return new;
  end if;

  if origin = 'scraper' then
    new.website := coalesce(new.website, old.website);
    new.domain := coalesce(new.domain, old.domain);
    new.description := coalesce(new.description, old.description);
    new.city := coalesce(new.city, old.city);
    new.state := coalesce(new.state, old.state);
    new.country := coalesce(new.country, old.country);
    new.location := coalesce(new.location, old.location);
    new.is_remote := coalesce(new.is_remote, old.is_remote);
    new.industry := coalesce(new.industry, old.industry);
    new.subindustry := coalesce(new.subindustry, old.subindustry);
    new.entity_kind := coalesce(new.entity_kind, old.entity_kind);
    new.employee_count := coalesce(new.employee_count, old.employee_count);
    new.status := coalesce(new.status, old.status);
    new.stage := coalesce(new.stage, old.stage);
    new.is_hiring := coalesce(new.is_hiring, old.is_hiring);
    new.logo_url := coalesce(new.logo_url, old.logo_url);
    new.accelerator_batch := coalesce(new.accelerator_batch, old.accelerator_batch);
    if new.founded_year is null
       or public.founded_source_rank(old.founded_source) > public.founded_source_rank(new.founded_source) then
      new.founded_year := old.founded_year;
      new.founded_on := old.founded_on;
      new.founded_source := old.founded_source;
    end if;
    new.metadata := coalesce(old.metadata, '{}'::jsonb) || coalesce(new.metadata, '{}'::jsonb);
  end if;

  -- Administrator edits win over both sources.
  new.edited_fields := old.edited_fields;
  if cardinality(old.edited_fields) > 0 then
    select jsonb_object_agg(field, to_jsonb(old) -> field)
      into keep
    from unnest(old.edited_fields) as field
    where to_jsonb(old) ? field;
    if keep is not null then
      new := jsonb_populate_record(new, keep);
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists startup_companies_protect_curated on public.startup_companies;
create trigger startup_companies_protect_curated
before update on public.startup_companies
for each row execute function public.protect_curated_company_fields();

-- Companies an administrator deleted stay deleted: the collector skips their source keys.
create table if not exists public.company_tombstones (
  source_key text primary key,
  name text,
  source_name text,
  deleted_by text,
  deleted_at timestamptz not null default now()
);

create or replace function public.skip_deleted_companies()
returns trigger language plpgsql as $$
declare
  origin text;
begin
  begin
    origin := coalesce(nullif(current_setting('request.headers', true), '')::json ->> 'x-data-origin', '');
  exception when others then
    origin := '';
  end;
  if origin = 'scraper' and exists (select 1 from public.company_tombstones t where t.source_key = new.source_key) then
    return null;
  end if;
  return new;
end;
$$;

drop trigger if exists startup_companies_skip_deleted on public.startup_companies;
create trigger startup_companies_skip_deleted
before insert on public.startup_companies
for each row execute function public.skip_deleted_companies();

-- Generic updated_at trigger for tables without first_seen_at (set_updated_at from 001
-- also copies first_seen_at and only fits the company/funding tables).
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- 6. Users, notes, view state, jobs
-- ---------------------------------------------------------------------------
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  role text not null default 'user' check (role in ('admin', 'user')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.company_notes (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.startup_companies(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  note text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (company_id, user_id)
);

create table if not exists public.company_views (
  company_id uuid not null references public.startup_companies(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  viewed boolean not null default true,
  viewed_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (company_id, user_id)
);

create table if not exists public.scrape_runs (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now()
);

alter table public.scrape_runs
  add column if not exists kind text not null default 'collect',
  add column if not exists requested_by uuid references auth.users(id) on delete set null,
  add column if not exists requested_by_email text,
  add column if not exists status text not null default 'queued',
  add column if not exists sources text[] not null default '{}',
  add column if not exists options jsonb not null default '{}'::jsonb,
  add column if not exists progress jsonb not null default '{}'::jsonb,
  add column if not exists log text[] not null default '{}',
  add column if not exists companies_found integer not null default 0,
  add column if not exists rounds_found integer not null default 0,
  add column if not exists companies_saved integer not null default 0,
  add column if not exists rounds_saved integer not null default 0,
  add column if not exists enriched_count integer not null default 0,
  add column if not exists websites_found integer not null default 0,
  add column if not exists careers_found integer not null default 0,
  add column if not exists founded_found integer not null default 0,
  add column if not exists error text,
  add column if not exists started_at timestamptz,
  add column if not exists completed_at timestamptz,
  add column if not exists updated_at timestamptz not null default now();

alter table public.scrape_runs drop constraint if exists scrape_runs_status_check;
alter table public.scrape_runs add constraint scrape_runs_status_check
  check (status in ('queued', 'running', 'completed', 'failed', 'cancelled'));
alter table public.scrape_runs drop constraint if exists scrape_runs_kind_check;
alter table public.scrape_runs add constraint scrape_runs_kind_check
  check (kind in ('collect', 'enrich'));

create index if not exists startup_companies_country_idx on public.startup_companies(country);
create index if not exists startup_companies_founded_year_idx on public.startup_companies(founded_year);
create index if not exists startup_companies_latest_round_on_idx on public.startup_companies(latest_round_on desc nulls last);
create index if not exists startup_companies_careers_idx on public.startup_companies(has_careers_page);
create index if not exists startup_companies_enriched_at_idx on public.startup_companies(enriched_at nulls first);
create index if not exists startup_companies_entity_kind_idx on public.startup_companies(entity_kind);
create index if not exists startup_companies_round_types_idx on public.startup_companies using gin(round_types);
create index if not exists company_notes_user_idx on public.company_notes(user_id, company_id);
create index if not exists company_views_user_idx on public.company_views(user_id, company_id) where viewed;
create index if not exists scrape_runs_created_at_idx on public.scrape_runs(created_at desc);

drop trigger if exists profiles_touch_updated_at on public.profiles;
create trigger profiles_touch_updated_at before update on public.profiles
for each row execute function public.touch_updated_at();
drop trigger if exists company_notes_touch_updated_at on public.company_notes;
create trigger company_notes_touch_updated_at before update on public.company_notes
for each row execute function public.touch_updated_at();
drop trigger if exists company_views_touch_updated_at on public.company_views;
create trigger company_views_touch_updated_at before update on public.company_views
for each row execute function public.touch_updated_at();
drop trigger if exists scrape_runs_touch_updated_at on public.scrape_runs;
create trigger scrape_runs_touch_updated_at before update on public.scrape_runs
for each row execute function public.touch_updated_at();

-- Every new Supabase Auth user gets a 'user' profile; promote administrators explicitly
-- (or list their emails in the backend's ADMIN_EMAILS setting).
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, email, role)
  values (new.id, new.email, 'user')
  on conflict (id) do update set email = excluded.email;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert or update of email on auth.users
for each row execute function public.handle_new_user();

insert into public.profiles (id, email)
select id, email from auth.users
on conflict (id) do update set email = excluded.email;

-- ---------------------------------------------------------------------------
-- 7. Search and facets (called by the backend through PostgREST RPC)
-- ---------------------------------------------------------------------------
create or replace function public.company_search_ids(p_user_id uuid, p jsonb)
returns setof uuid language sql stable set search_path = public as $$
  with x as (
    select
      case when nullif(btrim(p ->> 'q'), '') is null then null
           else '%' || replace(replace(replace(btrim(p ->> 'q'), '\', '\\'), '%', '\%'), '_', '\_') || '%' end as q,
      case when nullif(btrim(p ->> 'location'), '') is null then null
           else '%' || replace(replace(replace(btrim(p ->> 'location'), '\', '\\'), '%', '\%'), '_', '\_') || '%' end as location,
      public.jsonb_text_array(p -> 'countries') as countries,
      public.jsonb_text_array(p -> 'states') as states,
      public.jsonb_text_array(p -> 'industries') as industries,
      public.jsonb_text_array(p -> 'stages') as stages,
      public.jsonb_text_array(p -> 'statuses') as statuses,
      public.jsonb_text_array(p -> 'sources') as sources,
      public.jsonb_text_array(p -> 'batches') as batches,
      public.jsonb_text_array(p -> 'kinds') as kinds,
      public.jsonb_text_array(p -> 'round_types') as round_types,
      public.jsonb_text_array(p -> 'providers') as providers,
      public.jsonb_text_array(p -> 'website_statuses') as website_statuses,
      public.jsonb_text_array(p -> 'founded_sources') as founded_sources,
      case p ->> 'remote' when 'yes' then true when 'no' then false end as remote,
      case p ->> 'website' when 'yes' then true when 'no' then false end as website,
      nullif(p ->> 'careers', '') as careers,
      case p ->> 'hiring' when 'yes' then true when 'no' then false end as hiring,
      case p ->> 'viewed' when 'yes' then true when 'no' then false end as viewed,
      case p ->> 'notes' when 'yes' then true when 'no' then false end as has_note,
      case p ->> 'founded_known' when 'yes' then true when 'no' then false end as founded_known,
      case p ->> 'enriched' when 'yes' then true when 'no' then false end as enriched,
      nullif(p ->> 'min_jobs', '')::int as min_jobs,
      nullif(p ->> 'amount_min', '')::numeric as amount_min,
      nullif(p ->> 'amount_max', '')::numeric as amount_max,
      nullif(p ->> 'total_min', '')::numeric as total_min,
      nullif(p ->> 'total_max', '')::numeric as total_max,
      nullif(p ->> 'funded_after', '')::date as funded_after,
      nullif(p ->> 'funded_before', '')::date as funded_before,
      nullif(p ->> 'founded_from', '')::int as founded_from,
      nullif(p ->> 'founded_to', '')::int as founded_to,
      nullif(p ->> 'team_min', '')::int as team_min,
      nullif(p ->> 'team_max', '')::int as team_max,
      nullif(p ->> 'added_after', '')::timestamptz as added_after
  )
  select c.id
  from public.startup_companies c
  cross join x
  left join public.company_views v on v.company_id = c.id and v.user_id = p_user_id
  left join public.company_notes n on n.company_id = c.id and n.user_id = p_user_id
  where (x.q is null or c.name ilike x.q or c.description ilike x.q or c.domain ilike x.q
         or c.location ilike x.q or c.industry ilike x.q or c.subindustry ilike x.q)
    and (x.location is null or c.location ilike x.location or c.city ilike x.location
         or c.state ilike x.location or c.country ilike x.location)
    and (x.countries is null or c.country = any(x.countries))
    and (x.states is null or c.state = any(x.states))
    and (x.industries is null or c.industry = any(x.industries))
    and (x.stages is null or c.stage = any(x.stages))
    and (x.statuses is null or c.status = any(x.statuses))
    and (x.sources is null or c.source_name = any(x.sources))
    and (x.batches is null or c.accelerator_batch = any(x.batches))
    and (x.kinds is null or c.entity_kind = any(x.kinds))
    and (x.round_types is null or c.round_types && x.round_types)
    and (x.providers is null or c.careers_provider = any(x.providers))
    and (x.website_statuses is null or c.website_status = any(x.website_statuses))
    and (x.founded_sources is null or c.founded_source = any(x.founded_sources))
    and (x.remote is null or coalesce(c.is_remote, false) = x.remote)
    and (x.website is null or (c.website is not null) = x.website)
    and (x.careers is null
         or (x.careers = 'yes' and c.has_careers_page is true)
         or (x.careers = 'no' and c.has_careers_page is false)
         or (x.careers = 'unchecked' and c.careers_checked_at is null))
    and (x.hiring is null or (coalesce(c.is_hiring, false) or coalesce(c.open_jobs_count, 0) > 0) = x.hiring)
    and (x.min_jobs is null or coalesce(c.open_jobs_count, 0) >= x.min_jobs)
    and (x.amount_min is null or c.latest_amount_usd >= x.amount_min)
    and (x.amount_max is null or c.latest_amount_usd <= x.amount_max)
    and (x.total_min is null or c.total_funding_usd >= x.total_min)
    and (x.total_max is null or c.total_funding_usd <= x.total_max)
    and (x.funded_after is null or c.latest_round_on >= x.funded_after)
    and (x.funded_before is null or c.latest_round_on <= x.funded_before)
    and (x.founded_from is null or c.founded_year >= x.founded_from)
    and (x.founded_to is null or c.founded_year <= x.founded_to)
    and (x.founded_known is null or (c.founded_year is not null) = x.founded_known)
    and (x.team_min is null or c.employee_count >= x.team_min)
    and (x.team_max is null or c.employee_count <= x.team_max)
    and (x.viewed is null or coalesce(v.viewed, false) = x.viewed)
    and (x.has_note is null or (coalesce(btrim(n.note), '') <> '') = x.has_note)
    and (x.enriched is null or (c.enriched_at is not null) = x.enriched)
    and (x.added_after is null or c.first_seen_at >= x.added_after);
$$;

create or replace function public.search_companies(p_user_id uuid, p jsonb default '{}'::jsonb)
returns jsonb language plpgsql stable set search_path = public as $$
declare
  v_sort text := coalesce(nullif(p ->> 'sort', ''), 'funded');
  v_limit int := least(greatest(coalesce(nullif(p ->> 'limit', '')::int, 25), 1), 5000);
  v_offset int := greatest(coalesce(nullif(p ->> 'offset', '')::int, 0), 0);
  v_total bigint := 0;
  v_rows jsonb;
begin
  select coalesce(jsonb_agg(to_jsonb(r) - 'total_count' - 'sort_rank' order by r.sort_rank), '[]'::jsonb),
         coalesce(max(r.total_count), 0)
    into v_rows, v_total
  from (
    select
      c.id, c.name, c.website, c.domain, left(c.description, 400) as description,
      c.location, c.city, c.state, c.country, c.is_remote,
      c.industry, c.subindustry, c.stage, c.status, c.entity_kind, c.accelerator_batch,
      c.employee_count, c.founded_year, c.founded_on, c.founded_source,
      c.website_status, c.website_discovery_source,
      c.has_careers_page, c.careers_url, c.careers_provider, c.open_jobs_count, c.careers_checked_at,
      c.is_hiring, c.latest_round_type, c.latest_round_on, c.latest_amount_usd, c.total_funding_usd,
      c.round_count, c.source_name, c.source_url, c.logo_url,
      c.first_seen_at, c.last_seen_at, c.enriched_at,
      coalesce(v.viewed, false) as viewed, v.viewed_at,
      n.note, n.updated_at as note_updated_at,
      count(*) over () as total_count,
      row_number() over (order by
        case when v_sort = 'name' then lower(c.name) end asc,
        case when v_sort = 'founded_desc' then c.founded_year end desc nulls last,
        case when v_sort = 'founded_asc' then c.founded_year end asc nulls last,
        case when v_sort = 'funded' then c.latest_round_on end desc nulls last,
        case when v_sort = 'amount' then c.latest_amount_usd end desc nulls last,
        case when v_sort = 'total' then c.total_funding_usd end desc nulls last,
        case when v_sort = 'team' then c.employee_count end desc nulls last,
        case when v_sort = 'jobs' then c.open_jobs_count end desc nulls last,
        case when v_sort = 'added' then c.first_seen_at end desc,
        c.first_seen_at desc, c.id
      ) as sort_rank
    from public.company_search_ids(p_user_id, p) as m(id)
    join public.startup_companies c on c.id = m.id
    left join public.company_views v on v.company_id = c.id and v.user_id = p_user_id
    left join public.company_notes n on n.company_id = c.id and n.user_id = p_user_id
    order by sort_rank
    limit v_limit offset v_offset
  ) r;

  if jsonb_array_length(v_rows) = 0 and v_offset > 0 then
    select count(*) into v_total from public.company_search_ids(p_user_id, p);
  end if;
  return jsonb_build_object('total', v_total, 'rows', v_rows);
end;
$$;

create or replace function public.company_facets()
returns jsonb language plpgsql stable set search_path = public as $$
declare
  result jsonb := '{}'::jsonb;
  facet record;
  values_json jsonb;
begin
  for facet in
    select * from (values
      ('countries', 'country'), ('industries', 'industry'), ('stages', 'stage'),
      ('statuses', 'status'), ('sources', 'source_name'), ('batches', 'accelerator_batch'),
      ('kinds', 'entity_kind'), ('providers', 'careers_provider'), ('website_statuses', 'website_status'),
      ('founded_sources', 'founded_source')
    ) as f(key, col)
  loop
    execute format(
      'select coalesce(jsonb_agg(jsonb_build_object(''value'', v, ''count'', n) order by n desc, v), ''[]''::jsonb)
         from (select %1$I as v, count(*) as n from public.startup_companies where %1$I is not null group by %1$I) s',
      facet.col
    ) into values_json;
    result := result || jsonb_build_object(facet.key, values_json);
  end loop;

  select coalesce(jsonb_agg(jsonb_build_object('value', v, 'count', n) order by n desc, v), '[]'::jsonb)
    into values_json
  from (
    select unnest(round_types) as v, count(*) as n
    from public.startup_companies
    group by 1
  ) s;
  result := result || jsonb_build_object('round_types', values_json);

  -- States are only meaningful together with their country.
  select coalesce(jsonb_agg(jsonb_build_object('value', state, 'country', country, 'count', n) order by n desc, state), '[]'::jsonb)
    into values_json
  from (
    select state, country, count(*) as n
    from public.startup_companies
    where state is not null
    group by state, country
  ) s;
  result := result || jsonb_build_object('states', values_json);

  select result || jsonb_build_object(
    'founded_min', min(founded_year),
    'founded_max', max(founded_year),
    'total', count(*)
  ) into result
  from public.startup_companies;
  return result;
end;
$$;

create or replace function public.company_coverage()
returns jsonb language sql stable set search_path = public as $$
  select jsonb_build_object(
    'total', count(*),
    'with_website', count(*) filter (where website is not null),
    'website_verified', count(*) filter (where website_status = 'verified'),
    'website_not_found', count(*) filter (where website is null and website_status = 'not_found'),
    'never_enriched', count(*) filter (where enriched_at is null),
    'careers_checked', count(*) filter (where careers_checked_at is not null),
    'with_careers', count(*) filter (where has_careers_page),
    'hiring', count(*) filter (where coalesce(is_hiring, false) or coalesce(open_jobs_count, 0) > 0),
    'founded_known', count(*) filter (where founded_year is not null),
    'founded_estimated', count(*) filter (where founded_source in ('yc_batch_estimate', 'domain_registration', 'website_copyright')),
    'startups', count(*) filter (where entity_kind = 'startup'),
    'by_source', (
      select coalesce(jsonb_agg(jsonb_build_object('source', source_name, 'total', n, 'with_website', w) order by n desc), '[]'::jsonb)
      from (
        select source_name, count(*) as n, count(*) filter (where website is not null) as w
        from public.startup_companies group by source_name
      ) s
    )
  )
  from public.startup_companies;
$$;

-- ---------------------------------------------------------------------------
-- 8. Privileges: only the backend (service_role) touches these objects
-- ---------------------------------------------------------------------------
alter table public.profiles enable row level security;
alter table public.company_notes enable row level security;
alter table public.company_views enable row level security;
alter table public.scrape_runs enable row level security;
alter table public.company_tombstones enable row level security;

revoke all on public.profiles, public.company_notes, public.company_views, public.scrape_runs, public.company_tombstones
  from anon, authenticated;
grant select, insert, update, delete
  on public.profiles, public.company_notes, public.company_views, public.scrape_runs, public.company_tombstones
  to service_role;

do $$
declare
  fn text;
begin
  foreach fn in array array[
    'public.search_companies(uuid, jsonb)',
    'public.company_search_ids(uuid, jsonb)',
    'public.company_facets()',
    'public.company_coverage()',
    'public.refresh_company_funding(uuid)'
  ] loop
    execute format('revoke all on function %s from public, anon, authenticated', fn);
    execute format('grant execute on function %s to service_role', fn);
  end loop;
end;
$$;

-- Ask PostgREST to pick up the new columns and functions immediately.
notify pgrst, 'reload schema';

-- After applying, promote your first administrator (or set ADMIN_EMAILS for the backend):
-- update public.profiles set role = 'admin' where email = 'you@example.com';
