export type Role = "admin" | "user";

export type Me = { id: string; email: string; role: Role };

export type FundingRound = {
  id: string;
  company_id: string;
  announced_on: string | null;
  round_type: string | null;
  amount: number | null;
  currency: string | null;
  amount_usd: number | null;
  valuation: number | null;
  valuation_currency: string | null;
  valuation_usd: number | null;
  investors: string[];
  title: string | null;
  summary: string | null;
  source_name: string;
  source_url: string;
};

export type CompanyRow = {
  id: string;
  name: string;
  website: string | null;
  domain: string | null;
  description: string | null;
  location: string | null;
  city: string | null;
  state: string | null;
  country: string | null;
  is_remote: boolean | null;
  industry: string | null;
  subindustry: string | null;
  sectors: string[] | null;
  stage: string | null;
  status: string | null;
  entity_kind: string | null;
  accelerator_batch: string | null;
  employee_count: number | null;
  founded_year: number | null;
  founded_on: string | null;
  founded_source: string | null;
  website_status: string | null;
  website_discovery_source: string | null;
  has_careers_page: boolean | null;
  careers_url: string | null;
  careers_provider: string | null;
  open_jobs_count: number | null;
  careers_checked_at: string | null;
  is_hiring: boolean | null;
  latest_round_type: string | null;
  latest_round_on: string | null;
  latest_amount_usd: number | null;
  total_funding_usd: number | null;
  latest_valuation_usd: number | null;
  investors: string[] | null;
  round_count: number;
  linkedin_url: string | null;
  twitter_url: string | null;
  github_url: string | null;
  contact_email: string | null;
  source_name: string;
  source_url: string;
  logo_url: string | null;
  first_seen_at: string;
  last_seen_at: string;
  enriched_at: string | null;
  viewed: boolean;
  viewed_at: string | null;
  note: string | null;
  note_updated_at: string | null;
};

export type CompanyDetail = CompanyRow & {
  funding_rounds: FundingRound[];
  metadata: Record<string, unknown> | null;
  edited_fields: string[] | null;
  domain_registered_on: string | null;
  website_verified_at: string | null;
  enrichment_error: string | null;
};

export type CompanyPage = {
  companies: CompanyRow[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
};

export type FacetValue = { value: string; count: number; country?: string };

export type Facets = {
  countries: FacetValue[];
  states: FacetValue[];
  industries: FacetValue[];
  sectors: FacetValue[];
  stages: FacetValue[];
  statuses: FacetValue[];
  sources: FacetValue[];
  batches: FacetValue[];
  kinds: FacetValue[];
  providers: FacetValue[];
  website_statuses: FacetValue[];
  founded_sources: FacetValue[];
  round_types: FacetValue[];
  founded_min: number | null;
  founded_max: number | null;
  total: number;
};

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type Job = {
  id: string;
  kind: "collect" | "enrich";
  status: JobStatus;
  sources?: string[];
  options: Record<string, unknown>;
  progress: { stage?: string; processed?: number; total?: number; errors?: number };
  log?: string[];
  error: string | null;
  companies_found: number;
  rounds_found: number;
  companies_saved: number;
  rounds_saved: number;
  enriched_count: number;
  websites_found: number;
  careers_found: number;
  founded_found: number;
  contacts_found?: number;
  requested_by_email?: string | null;
  created_at?: string;
  started_at: string | null;
  completed_at?: string | null;
};

export type Coverage = {
  total: number;
  with_website: number;
  website_verified: number;
  website_not_found: number;
  never_enriched: number;
  careers_checked: number;
  with_careers: number;
  hiring: number;
  founded_known: number;
  founded_estimated: number;
  startups: number;
  with_contact_email?: number;
  with_linkedin?: number;
  with_social?: number;
  with_sector?: number;
  with_investors?: number;
  by_source: Array<{ source: string; total: number; with_website: number }>;
};

export type Profile = { id: string; email: string | null; role: Role; created_at: string };

export type Tombstone = { source_key: string; name: string | null; source_name: string | null; deleted_by: string | null; deleted_at: string };
