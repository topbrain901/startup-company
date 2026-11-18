-- Run this in the Supabase SQL editor, then use a server-side service-role key.
create extension if not exists pgcrypto;

create table if not exists public.startup_companies (
  id uuid primary key default gen_random_uuid(),
  source_key text not null unique,
  source_name text not null,
  source_id text not null,
  source_url text not null,
  name text not null,
  normalized_name text not null,
  website text,
  domain text,
  description text,
  city text,
  state text,
  country text,
  location text,
  industry text,
  subindustry text,
  founded_year integer,
  employee_count integer,
  status text,
  accelerator_batch text,
  stage text,
  is_hiring boolean,
  logo_url text,
  metadata jsonb not null default '{}'::jsonb,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.funding_rounds (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.startup_companies(id) on delete cascade,
  source_key text not null unique,
  source_name text not null,
  source_url text not null,
  announced_on date,
  round_type text,
  amount numeric,
  currency text,
  amount_usd numeric,
  investors text[] not null default '{}',
  title text,
  summary text,
  metadata jsonb not null default '{}'::jsonb,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists startup_companies_normalized_name_idx on public.startup_companies(normalized_name);
create index if not exists startup_companies_domain_idx on public.startup_companies(domain) where domain is not null;
create index if not exists startup_companies_industry_idx on public.startup_companies(industry);
create index if not exists funding_rounds_company_id_idx on public.funding_rounds(company_id);
create index if not exists funding_rounds_announced_on_idx on public.funding_rounds(announced_on desc);
create index if not exists funding_rounds_amount_usd_idx on public.funding_rounds(amount_usd desc);

alter table public.startup_companies enable row level security;
alter table public.funding_rounds enable row level security;

-- The collector is a trusted server process. Do not grant anon write access.
revoke all on public.startup_companies from anon, authenticated;
revoke all on public.funding_rounds from anon, authenticated;
grant select, insert, update, delete on public.startup_companies to service_role;
grant select, insert, update, delete on public.funding_rounds to service_role;

create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  new.first_seen_at = old.first_seen_at;
  return new;
end;
$$;

drop trigger if exists startup_companies_set_updated_at on public.startup_companies;
create trigger startup_companies_set_updated_at before update on public.startup_companies
for each row execute function public.set_updated_at();

drop trigger if exists funding_rounds_set_updated_at on public.funding_rounds;
create trigger funding_rounds_set_updated_at before update on public.funding_rounds
for each row execute function public.set_updated_at();

