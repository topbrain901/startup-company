const compactMoney = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
});

export function money(value: number | null | undefined): string {
  return value ? compactMoney.format(value) : "—";
}

export function shortDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value.length === 10 ? `${value}T00:00:00Z` : value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return "never";
  const diff = Date.now() - new Date(value).getTime();
  const minutes = Math.round(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 60) return `${days}d ago`;
  return shortDate(value);
}

export function duration(start: string | null | undefined, end: string | null | undefined): string {
  if (!start) return "—";
  const seconds = Math.max(0, Math.round(((end ? new Date(end) : new Date()).getTime() - new Date(start).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function initials(value: string): string {
  return value
    .split(/[\s\-_.,&()/+]+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase() || "?";
}

export function hostname(url: string | null | undefined): string {
  if (!url) return "";
  try {
    return new URL(url.includes("://") ? url : `https://${url}`).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function safeHref(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  try {
    const parsed = new URL(url.includes("://") ? url : `https://${url}`);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.toString() : undefined;
  } catch {
    return undefined;
  }
}

/** Last path segment of a profile URL: "https://x.com/acme" -> "@acme" with prefix "@". */
export function profileHandle(url: string | null | undefined, prefix = ""): string {
  if (!url) return "";
  try {
    const path = new URL(url).pathname.replace(/\/+$/, "");
    return prefix + decodeURIComponent(path.slice(path.lastIndexOf("/") + 1));
  } catch {
    return url;
  }
}

export function safeMailto(email: string | null | undefined): string | undefined {
  return email && /^[^\s@<>"?&]+@[^\s@<>"?&]+\.[a-z]{2,}$/i.test(email) ? `mailto:${email}` : undefined;
}

export function percent(part: number, total: number): string {
  return total ? `${Math.round((part / total) * 100)}%` : "0%";
}

export const KIND_LABELS: Record<string, string> = {
  startup: "Startup / operating company",
  investment_vehicle: "Fund / investment vehicle",
  real_estate: "Real estate",
  other: "Other business",
};

export const PROVIDER_LABELS: Record<string, string> = {
  website: "Company website",
  manual: "Added manually",
  yc: "YC Work at a Startup",
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  workable: "Workable",
  smartrecruiters: "SmartRecruiters",
  recruitee: "Recruitee",
  teamtailor: "Teamtailor",
  personio: "Personio",
  bamboohr: "BambooHR",
  breezy: "Breezy HR",
  jazzhr: "JazzHR",
  workday: "Workday",
  rippling: "Rippling",
  jobvite: "Jobvite",
  icims: "iCIMS",
  pinpoint: "Pinpoint",
  dover: "Dover",
  wellfound: "Wellfound",
  join: "JOIN",
  homerun: "Homerun",
};

export const FOUNDED_SOURCE_LABELS: Record<string, string> = {
  manual: "set by admin",
  sec_form_d: "SEC filing",
  yc_profile: "YC profile",
  wikidata: "Wikidata",
  fundingwatcher: "FundingWatcher",
  website_structured_data: "company website",
  website_text: "company website",
  yc_batch_estimate: "estimated from YC batch",
  domain_registration: "estimated from domain registration",
  website_copyright: "estimated from site copyright",
  legacy: "imported",
};

export const ESTIMATED_FOUNDED = new Set(["yc_batch_estimate", "domain_registration", "website_copyright"]);

export const WEBSITE_STATUS_LABELS: Record<string, string> = {
  verified: "Verified",
  unverified: "Not verified",
  unreachable: "Unreachable",
  not_found: "Not found",
};

export const DISCOVERY_LABELS: Record<string, string> = {
  yc_profile: "YC profile",
  news_article: "funding article",
  wikidata: "Wikidata",
  domain_guess: "name-based domain check",
  search_api: "search API",
  manual: "admin",
  existing: "source data",
};

export function label(map: Record<string, string>, value: string | null | undefined): string {
  if (!value) return "—";
  return map[value] || value.replace(/_/g, " ").replace(/^\w/, (char) => char.toUpperCase());
}
