// Filter state for the companies table. It is mirrored into the page URL so a filtered view
// can be bookmarked or shared, and it maps 1:1 onto the backend's /companies query params.

export type YesNo = "" | "yes" | "no";

export type Filters = {
  q: string;
  location: string;
  country: string[];
  state: string[];
  industry: string[];
  stage: string[];
  status: string[];
  source: string[];
  batch: string[];
  kind: string[];
  round_type: string[];
  provider: string[];
  remote: YesNo;
  website: YesNo;
  careers: "" | "yes" | "no" | "unchecked";
  hiring: YesNo;
  viewed: YesNo;
  notes: YesNo;
  founded_known: YesNo;
  min_jobs: string;
  amount_min: string;
  amount_max: string;
  total_min: string;
  funded_within: string;
  founded_from: string;
  founded_to: string;
  team_min: string;
  team_max: string;
  added_within: string;
  sort: string;
};

export const ARRAY_KEYS = [
  "country", "state", "industry", "stage", "status", "source", "batch", "kind", "round_type", "provider",
] as const;

export const EMPTY_FILTERS: Filters = {
  q: "", location: "", country: [], state: [], industry: [], stage: [], status: [], source: [], batch: [],
  kind: [], round_type: [], provider: [], remote: "", website: "", careers: "", hiring: "", viewed: "",
  notes: "", founded_known: "", min_jobs: "", amount_min: "", amount_max: "", total_min: "", funded_within: "",
  founded_from: "", founded_to: "", team_min: "", team_max: "", added_within: "", sort: "funded",
};

export const SORT_OPTIONS = [
  { value: "funded", label: "Most recently funded" },
  { value: "amount", label: "Largest latest round" },
  { value: "total", label: "Most total funding" },
  { value: "jobs", label: "Most open jobs" },
  { value: "added", label: "Newest in database" },
  { value: "founded_desc", label: "Youngest companies" },
  { value: "founded_asc", label: "Oldest companies" },
  { value: "team", label: "Largest team" },
  { value: "name", label: "Name A–Z" },
];

export const FUNDED_WITHIN_OPTIONS = [
  { value: "", label: "Any time" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "180", label: "Last 6 months" },
  { value: "365", label: "Last 12 months" },
  { value: "730", label: "Last 2 years" },
];

export const ADDED_WITHIN_OPTIONS = [
  { value: "", label: "Any time" },
  { value: "1", label: "Last 24 hours" },
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
];

export const AMOUNT_OPTIONS = [
  { value: "", label: "Any" },
  { value: "100000", label: "$100K" },
  { value: "500000", label: "$500K" },
  { value: "1000000", label: "$1M" },
  { value: "5000000", label: "$5M" },
  { value: "10000000", label: "$10M" },
  { value: "25000000", label: "$25M" },
  { value: "50000000", label: "$50M" },
  { value: "100000000", label: "$100M" },
];

const SCALAR_KEYS = (Object.keys(EMPTY_FILTERS) as Array<keyof Filters>).filter(
  (key) => !(ARRAY_KEYS as readonly string[]).includes(key),
);

export function filtersFromSearch(search: string): Filters {
  const params = new URLSearchParams(search);
  const result: Filters = { ...EMPTY_FILTERS };
  for (const key of ARRAY_KEYS) result[key] = params.getAll(key).filter(Boolean);
  for (const key of SCALAR_KEYS) {
    const value = params.get(key);
    if (value !== null) (result as Record<string, unknown>)[key] = value;
  }
  return result;
}

export function filtersToParams(filters: Filters): Record<string, string | string[]> {
  const params: Record<string, string | string[]> = {};
  for (const [key, value] of Object.entries(filters)) {
    if (Array.isArray(value) ? value.length : value !== "" && !(key === "sort" && value === "funded")) {
      params[key] = value as string | string[];
    }
  }
  return params;
}

/** Number of active filters, excluding free-text search and sort order. */
export function activeFilterCount(filters: Filters): number {
  return Object.entries(filters).filter(([key, value]) =>
    key !== "q" && key !== "sort" && (Array.isArray(value) ? value.length > 0 : value !== ""),
  ).length;
}

export type QuickFilter = { label: string; apply: Partial<Filters>; active: (filters: Filters) => boolean };

export const QUICK_FILTERS: QuickFilter[] = [
  { label: "Not viewed", apply: { viewed: "no" }, active: (f) => f.viewed === "no" },
  { label: "Has careers page", apply: { careers: "yes" }, active: (f) => f.careers === "yes" },
  { label: "Hiring now", apply: { hiring: "yes" }, active: (f) => f.hiring === "yes" },
  { label: "Has website", apply: { website: "yes" }, active: (f) => f.website === "yes" },
  { label: "No website", apply: { website: "no" }, active: (f) => f.website === "no" },
  { label: "Startups only", apply: { kind: ["startup"] }, active: (f) => f.kind.length === 1 && f.kind[0] === "startup" },
  { label: "Funded ≤ 90 days", apply: { funded_within: "90" }, active: (f) => f.funded_within === "90" },
  { label: "Remote-friendly", apply: { remote: "yes" }, active: (f) => f.remote === "yes" },
  { label: "My notes", apply: { notes: "yes" }, active: (f) => f.notes === "yes" },
];
