-- Funding Radar 004: social profiles + contact email, round valuations, investors on the company row,
-- and a cross-source sector classification.
--
-- Run in the Supabase SQL editor after 003. Safe to re-run. Re-running 003 afterwards would put back
-- its older search functions: run 004 again if you ever do.

-- ---------------------------------------------------------------------------
-- 1. Columns
-- ---------------------------------------------------------------------------
alter table public.startup_companies
  add column if not exists linkedin_url text,
  add column if not exists twitter_url text,
  add column if not exists github_url text,
  add column if not exists contact_email text,
  add column if not exists investors text[] not null default '{}',
  add column if not exists latest_valuation_usd numeric,
  add column if not exists sectors text[] not null default '{}';

alter table public.funding_rounds
  add column if not exists valuation numeric,
  add column if not exists valuation_currency text,
  add column if not exists valuation_usd numeric;

alter table public.scrape_runs
  add column if not exists contacts_found integer not null default 0;

create index if not exists startup_companies_sectors_idx on public.startup_companies using gin(sectors);
create index if not exists startup_companies_investors_idx on public.startup_companies using gin(investors);
create index if not exists startup_companies_latest_valuation_idx on public.startup_companies(latest_valuation_usd desc nulls last);

-- ---------------------------------------------------------------------------
-- 2. Sectors: one taxonomy across YC industries, SEC industry groups, and news descriptions.
--    A company can be in several sectors ("AI for hospitals" is AI and Health).
-- ---------------------------------------------------------------------------
create or replace function public.classify_sectors(p_industry text, p_subindustry text, p_description text, p_tags jsonb)
returns text[] language sql immutable as $$
  with t as (
    select lower(concat_ws(' ',
      p_industry,
      p_subindustry,
      left(p_description, 3000),
      (select string_agg(tag, ' ')
         from jsonb_array_elements_text(case when jsonb_typeof(p_tags) = 'array' then p_tags else '[]'::jsonb end) as tag)
    )) as v
  )
  select coalesce(array_agg(s.sector order by s.sector), '{}')
  from t
  cross join (values
    ('AI & machine learning',
     '\m(ai|artificial intelligence|machine learning|ml|llms?|large language models?|genai|generative ai|deep learning|neural networks?|computer vision|nlp|natural language processing|ai agents?|agentic|copilots?|foundation models?)\M'),
    ('Fintech',
     '\m(fintech|payments?|banking|neobanks?|lending|lenders?|loans?|credit cards?|insurtech|insurance|wealthtech|wealth management|trading|brokerage|accounting|bookkeeping|payroll|invoic\w*|treasury|financial services|regtech|bnpl|buy now,? pay later|remittances?|money transfers?|expense management)\M'),
    ('Crypto & web3',
     '\m(crypto|cryptocurrenc\w*|blockchains?|web3|defi|stablecoins?|nfts?|bitcoin|ethereum|solana|on-?chain)\M'),
    ('Health & biotech',
     '\m(health\w*|medical|medtech|medicine|clinical|clinics?|patients?|hospitals?|biotech\w*|biology|pharma\w*|therapeutics?|therapy|therapies|drug discovery|drugs?|diagnostics?|genomics?|life sciences|telehealth|telemedicine|wellness|fitness|dental|veterinary|caregivers?|nursing)\M'),
    ('Energy & climate',
     '\m(climate|carbon|cleantech|clean tech|renewables?|solar|wind (power|energy|farms?)|batter(y|ies)|energy|hydrogen|ev charging|electric vehicles?|decarboni[sz]\w*|sustainability|sustainable (energy|materials|fashion|packaging|agriculture|aviation|food|products)|emissions|geothermal|nuclear|fusion energy|oil and gas|electric utilities|utility companies|recycling|circular economy|environmental)\M'),
    ('Developer tools & infrastructure',
     '\m(devtools?|developer (tools?|platforms?|experience|productivity|teams?|workflows?)|for developers|software developers?|apis?|sdks?|open[- ]source|infrastructure|cloud|databases?|devops|observability|kubernetes|serverless|data (platform|pipelines?|infrastructure|warehouses?|engineering)|ci/cd|low[- ]code|no[- ]code|software engineers?|engineering teams)\M'),
    ('Cybersecurity',
     '\m(security|cybersecurity|cyber\w*|fraud|threats?|vulnerabilit\w*|zero[- ]trust|encryption|authentication|identity verification|penetration testing)\M'),
    ('Consumer & commerce',
     '\m(e-?commerce|retail\w*|marketplaces?|consumers?|shopping|shoppers?|d2c|dtc|direct-to-consumer|fashion|apparel|beauty|cosmetics|grocer(y|ies)|restaurants?|food delivery|travel|tourism|hospitality|lodging|online dating|dating apps?|pets?)\M'),
    ('B2B software',
     '\m(saas|b2b|enterprise software|enterprises?|crm|erp|workflows?|productivity|collaboration|hr ?tech|human resources|recruiting|sales (teams?|platform|automation)|marketing (platform|automation|teams?)|customer (support|success|service)|procurement|back[- ]office)\M'),
    ('Hardware & robotics',
     '\m(robot\w*|hardware|semiconductors?|chips?|chipmakers?|3d printing|additive manufacturing|manufacturing|iot|internet of things|sensors?|lidar|wearables?|computers|electronics|photonics|quantum)\M'),
    ('Aerospace & defense',
     '\m(aerospace|space ?tech|spacecraft|satellites?|rockets?|launch vehicles?|orbital|defen[cs]e (tech|technology|industry|sector|contractors?|primes?|applications)|defense-tech|military|national security|department of defense|warfighters?|armed forces|aviation|aircraft|drones?)\M'),
    ('Mobility & logistics',
     '\m(logistics|supply chain|freight|last[- ]mile|fleets?|mobility|transportation|public transit|autonomous (vehicles?|driving|trucks?)|trucking|warehouse (automation|robotics|operations|management)|fulfil?lment|automotive|cars?|airlines|airports|ride[- ]?hailing|micromobility|scooters?)\M'),
    ('Education',
     '\m(edtech|education\w*|e-?learning|online (learning|courses?)|learning platforms?|students?|k-12|universit(y|ies)|tutor\w*|teachers?|classrooms?|upskilling|bootcamps?|school districts?|schools)\M'),
    ('Real estate & construction',
     '\m(real estate|proptech|propert(y|ies) (management|managers?|owners?|developers?|investors?|technology)|construction|contech|housing|mortgages?|landlords?|renters?|homebuyers?|reits?|residential|apartments?)\M'),
    ('Media & gaming',
     '\m(media|gaming|video games?|mobile games?|game (studios?|developers?|engines?)|esports|music|entertainment|creators?|creator economy|video streaming|live streaming|streaming (platforms?|services?)|podcasts?|social networks?|publishing|film|advertising|adtech)\M'),
    ('Food & agriculture',
     '\m(agtech|agri\w*|farm\w*|food\w*|beverages?|crops?|alternative proteins?|alt[- ]protein|plant-based|dairy|aquaculture)\M')
  ) as s(sector, pattern)
  where t.v ~ s.pattern;
$$;

create or replace function public.set_company_sectors()
returns trigger language plpgsql as $$
begin
  new.sectors := public.classify_sectors(new.industry, new.subindustry, new.description, new.metadata -> 'tags');
  return new;
end;
$$;

-- Named to sort after startup_companies_protect_curated: BEFORE triggers run in name order, so
-- sectors are computed from the values that trigger keeps.
drop trigger if exists startup_companies_set_sectors on public.startup_companies;
create trigger startup_companies_set_sectors
before insert or update of industry, subindustry, description, metadata on public.startup_companies
for each row execute function public.set_company_sectors();

update public.startup_companies
set sectors = public.classify_sectors(industry, subindustry, description, metadata -> 'tags')
where sectors is distinct from public.classify_sectors(industry, subindustry, description, metadata -> 'tags');

-- ---------------------------------------------------------------------------
-- 3. Social profiles the YC profile reader already stored in metadata
-- ---------------------------------------------------------------------------
update public.startup_companies
set linkedin_url = rtrim(regexp_replace(metadata ->> 'linkedin_url', '^https?://([a-z]{2,3}\.)?linkedin\.com/', 'https://www.linkedin.com/', 'i'), '/')
where linkedin_url is null
  and metadata ->> 'linkedin_url' ~* '^https?://([a-z]{2,3}\.)?linkedin\.com/(company|school|showcase)/[^/?#]+';

update public.startup_companies
set twitter_url = 'https://x.com/' || (regexp_match(metadata ->> 'twitter_url', '^https?://(?:www\.|mobile\.)?(?:twitter|x)\.com/@?([A-Za-z0-9_]{1,15})/?$', 'i'))[1]
where twitter_url is null
  and metadata ->> 'twitter_url' ~* '^https?://(www\.|mobile\.)?(twitter|x)\.com/@?[A-Za-z0-9_]{1,15}/?$';

update public.startup_companies
set github_url = 'https://github.com/' || (regexp_match(metadata ->> 'github_url', '^https?://(?:www\.)?github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38})/?$', 'i'))[1]
where github_url is null
  and metadata ->> 'github_url' ~* '^https?://(www\.)?github\.com/[A-Za-z0-9][A-Za-z0-9-]{0,38}/?$';

-- ---------------------------------------------------------------------------
-- 4. Funding summary: + investors (all rounds) and the most recent known valuation
-- ---------------------------------------------------------------------------
create or replace function public.refresh_company_funding(p_company uuid)
returns void language sql as $$
  update public.startup_companies c
  set round_count = s.cnt,
      total_funding_usd = s.total,
      latest_round_on = s.latest_on,
      latest_round_type = s.latest_type,
      latest_amount_usd = s.latest_amount,
      latest_valuation_usd = s.latest_valuation,
      round_types = s.types,
      investors = s.investor_names
  from (
    select
      count(*)::int as cnt,
      sum(amount_usd) as total,
      (array_agg(announced_on order by announced_on desc nulls last, created_at desc))[1] as latest_on,
      (array_agg(round_type order by announced_on desc nulls last, created_at desc))[1] as latest_type,
      (array_agg(amount_usd order by announced_on desc nulls last, created_at desc))[1] as latest_amount,
      (array_agg(valuation_usd order by announced_on desc nulls last, created_at desc)
         filter (where valuation_usd is not null))[1] as latest_valuation,
      coalesce(array_agg(distinct round_type) filter (where round_type is not null), '{}') as types,
      coalesce((
        select array_agg(distinct btrim(name) order by btrim(name))
        from public.funding_rounds r, unnest(r.investors) as name
        where r.company_id = p_company and btrim(name) <> ''
      ), '{}') as investor_names
    from public.funding_rounds
    where company_id = p_company
  ) s
  where c.id = p_company;
$$;

-- Backfill in one pass.
update public.startup_companies c
set latest_valuation_usd = s.latest_valuation,
    investors = s.investor_names
from (
  select
    f.company_id,
    (array_agg(f.valuation_usd order by f.announced_on desc nulls last, f.created_at desc)
       filter (where f.valuation_usd is not null))[1] as latest_valuation,
    coalesce((
      select array_agg(distinct btrim(name) order by btrim(name))
      from public.funding_rounds r, unnest(r.investors) as name
      where r.company_id = f.company_id and btrim(name) <> ''
    ), '{}') as investor_names
  from public.funding_rounds f
  group by f.company_id
) s
where c.id = s.company_id
  and (c.investors is distinct from s.investor_names or c.latest_valuation_usd is distinct from s.latest_valuation);

-- ---------------------------------------------------------------------------
-- 5. Search and facets (replaces the 003 versions; same signatures)
-- ---------------------------------------------------------------------------
create or replace function public.company_search_ids(p_user_id uuid, p jsonb)
returns setof uuid language sql stable set search_path = public as $$
  with x as (
    select
      case when nullif(btrim(p ->> 'q'), '') is null then null
           else '%' || replace(replace(replace(btrim(p ->> 'q'), '\', '\\'), '%', '\%'), '_', '\_') || '%' end as q,
      case when nullif(btrim(p ->> 'location'), '') is null then null
           else '%' || replace(replace(replace(btrim(p ->> 'location'), '\', '\\'), '%', '\%'), '_', '\_') || '%' end as location,
      case when nullif(btrim(p ->> 'investor'), '') is null then null
           else '%' || replace(replace(replace(btrim(p ->> 'investor'), '\', '\\'), '%', '\%'), '_', '\_') || '%' end as investor,
      public.jsonb_text_array(p -> 'countries') as countries,
      public.jsonb_text_array(p -> 'states') as states,
      public.jsonb_text_array(p -> 'industries') as industries,
      public.jsonb_text_array(p -> 'sectors') as sectors,
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
      case p ->> 'email' when 'yes' then true when 'no' then false end as has_email,
      case p ->> 'linkedin' when 'yes' then true when 'no' then false end as has_linkedin,
      case p ->> 'viewed' when 'yes' then true when 'no' then false end as viewed,
      case p ->> 'notes' when 'yes' then true when 'no' then false end as has_note,
      case p ->> 'founded_known' when 'yes' then true when 'no' then false end as founded_known,
      case p ->> 'enriched' when 'yes' then true when 'no' then false end as enriched,
      nullif(p ->> 'min_jobs', '')::int as min_jobs,
      nullif(p ->> 'amount_min', '')::numeric as amount_min,
      nullif(p ->> 'amount_max', '')::numeric as amount_max,
      nullif(p ->> 'total_min', '')::numeric as total_min,
      nullif(p ->> 'total_max', '')::numeric as total_max,
      nullif(p ->> 'valuation_min', '')::numeric as valuation_min,
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
         or c.location ilike x.q or c.industry ilike x.q or c.subindustry ilike x.q
         or array_to_string(c.investors, ' | ') ilike x.q)
    and (x.location is null or c.location ilike x.location or c.city ilike x.location
         or c.state ilike x.location or c.country ilike x.location)
    and (x.investor is null or array_to_string(c.investors, ' | ') ilike x.investor)
    and (x.countries is null or c.country = any(x.countries))
    and (x.states is null or c.state = any(x.states))
    and (x.industries is null or c.industry = any(x.industries))
    and (x.sectors is null or c.sectors && x.sectors)
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
    and (x.has_email is null or (c.contact_email is not null) = x.has_email)
    and (x.has_linkedin is null or (c.linkedin_url is not null) = x.has_linkedin)
    and (x.min_jobs is null or coalesce(c.open_jobs_count, 0) >= x.min_jobs)
    and (x.amount_min is null or c.latest_amount_usd >= x.amount_min)
    and (x.amount_max is null or c.latest_amount_usd <= x.amount_max)
    and (x.total_min is null or c.total_funding_usd >= x.total_min)
    and (x.total_max is null or c.total_funding_usd <= x.total_max)
    and (x.valuation_min is null or c.latest_valuation_usd >= x.valuation_min)
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
      c.industry, c.subindustry, c.sectors, c.stage, c.status, c.entity_kind, c.accelerator_batch,
      c.employee_count, c.founded_year, c.founded_on, c.founded_source,
      c.website_status, c.website_discovery_source,
      c.has_careers_page, c.careers_url, c.careers_provider, c.open_jobs_count, c.careers_checked_at,
      c.is_hiring, c.latest_round_type, c.latest_round_on, c.latest_amount_usd, c.total_funding_usd,
      c.latest_valuation_usd, c.investors, c.round_count,
      c.linkedin_url, c.twitter_url, c.github_url, c.contact_email,
      c.source_name, c.source_url, c.logo_url,
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
        case when v_sort = 'valuation' then c.latest_valuation_usd end desc nulls last,
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

  for facet in select * from (values ('round_types', 'round_types'), ('sectors', 'sectors')) as f(key, col)
  loop
    execute format(
      'select coalesce(jsonb_agg(jsonb_build_object(''value'', v, ''count'', n) order by n desc, v), ''[]''::jsonb)
         from (select unnest(%1$I) as v, count(*) as n from public.startup_companies group by 1) s',
      facet.col
    ) into values_json;
    result := result || jsonb_build_object(facet.key, values_json);
  end loop;

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
    'with_contact_email', count(*) filter (where contact_email is not null),
    'with_linkedin', count(*) filter (where linkedin_url is not null),
    'with_social', count(*) filter (where linkedin_url is not null or twitter_url is not null or github_url is not null),
    'with_sector', count(*) filter (where cardinality(sectors) > 0),
    'with_investors', count(*) filter (where cardinality(investors) > 0),
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
-- 6. Privileges (create or replace keeps grants; this also covers a fresh database)
-- ---------------------------------------------------------------------------
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

notify pgrst, 'reload schema';
