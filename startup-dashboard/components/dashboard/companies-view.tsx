"use client";

import {
  ArrowDown,
  ArrowUp,
  Briefcase,
  CheckCheck,
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  Plus,
  RefreshCw,
  Search,
  SlidersHorizontal,
  StickyNote,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, query } from "../../lib/api";
import {
  ESTIMATED_FOUNDED,
  FOUNDED_SOURCE_LABELS,
  KIND_LABELS,
  PROVIDER_LABELS,
  hostname,
  initials,
  label,
  money,
  safeHref,
  shortDate,
} from "../../lib/format";
import {
  ADDED_WITHIN_OPTIONS,
  AMOUNT_OPTIONS,
  ARRAY_KEYS,
  EMPTY_FILTERS,
  FUNDED_WITHIN_OPTIONS,
  QUICK_FILTERS,
  SORT_OPTIONS,
  activeFilterCount,
  filtersFromSearch,
  filtersToParams,
  type Filters,
} from "../../lib/filters";
import type { CompanyDetail, CompanyPage, CompanyRow, Facets } from "../../lib/types";
import CompanyDrawer from "./company-drawer";
import CompanyForm from "./company-form";
import FilterPanel from "./filter-panel";

type Notify = (message: string, tone?: "info" | "error" | "success") => void;

const PAGE_SIZES = [25, 50, 100];
const SCALAR_LABELS: Partial<Record<keyof Filters, (value: string) => string>> = {
  location: (value) => `Place: ${value}`,
  remote: (value) => (value === "yes" ? "Remote" : "On-site"),
  website: (value) => (value === "yes" ? "Has website" : "No website"),
  careers: (value) => ({ yes: "Has careers page", no: "No careers page", unchecked: "Careers not checked" })[value] || value,
  hiring: (value) => (value === "yes" ? "Hiring" : "Not hiring"),
  viewed: (value) => (value === "yes" ? "Viewed" : "Not viewed"),
  notes: (value) => (value === "yes" ? "With my note" : "Without my note"),
  founded_known: (value) => (value === "yes" ? "Founding date known" : "Founding date unknown"),
  min_jobs: (value) => `≥ ${value} open jobs`,
  amount_min: (value) => `Latest round ≥ ${optionLabel(AMOUNT_OPTIONS, value)}`,
  amount_max: (value) => `Latest round ≤ ${optionLabel(AMOUNT_OPTIONS, value)}`,
  total_min: (value) => `Raised ≥ ${optionLabel(AMOUNT_OPTIONS, value)}`,
  funded_within: (value) => `Funded: ${optionLabel(FUNDED_WITHIN_OPTIONS, value).toLowerCase()}`,
  added_within: (value) => `Added: ${optionLabel(ADDED_WITHIN_OPTIONS, value).toLowerCase()}`,
  founded_from: (value) => `Founded ≥ ${value}`,
  founded_to: (value) => `Founded ≤ ${value}`,
  team_min: (value) => `Team ≥ ${value}`,
  team_max: (value) => `Team ≤ ${value}`,
};
const ARRAY_PREFIX: Record<string, string> = {
  country: "", state: "", industry: "", stage: "Stage: ", status: "Status: ", source: "Source: ",
  batch: "YC ", kind: "", round_type: "", provider: "Jobs on ",
};

function roundLabel(value: string | null) {
  if (!value) return "—";
  return value === "Regulation D exempt offering" ? "Form D offering" : value;
}

function optionLabel(options: Array<{ value: string; label: string }>, value: string) {
  return options.find((option) => option.value === value)?.label || value;
}

function arrayChipLabel(key: string, value: string) {
  if (key === "kind") return label(KIND_LABELS, value);
  if (key === "provider") return `Jobs on ${label(PROVIDER_LABELS, value)}`;
  return `${ARRAY_PREFIX[key] || ""}${value}`;
}

const SORTABLE: Record<string, { desc: string; asc?: string }> = {
  name: { desc: "name", asc: "name" },
  funded: { desc: "funded" },
  total: { desc: "total" },
  founded: { desc: "founded_desc", asc: "founded_asc" },
  jobs: { desc: "jobs" },
};

function initialFromUrl() {
  // Rendered only in the browser (after the session check); the guard keeps SSR safe.
  const search = typeof window === "undefined" ? "" : window.location.search;
  const params = new URLSearchParams(search);
  const filters = filtersFromSearch(search);
  const size = Number(params.get("page_size"));
  return {
    filters,
    page: Math.max(1, Number(params.get("page")) || 1),
    pageSize: PAGE_SIZES.includes(size) ? size : 25,
    showFilters: typeof window !== "undefined" && activeFilterCount(filters) > 0 && window.innerWidth > 900,
  };
}

export default function CompaniesView({ isAdmin, notify }: { isAdmin: boolean; notify: Notify }) {
  const [initial] = useState(initialFromUrl);
  const [filters, setFilters] = useState<Filters>(initial.filters);
  const [searchText, setSearchText] = useState(initial.filters.q);
  const [page, setPage] = useState(initial.page);
  const [pageSize, setPageSize] = useState(initial.pageSize);
  const [data, setData] = useState<CompanyPage | null>(null);
  const [facets, setFacets] = useState<Facets | null>(null);
  const [settledKey, setSettledKey] = useState("");
  const [error, setError] = useState("");
  const [showFilters, setShowFilters] = useState(initial.showFilters);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  // Debounce free-text search; typing starts again from page 1.
  const typed = useRef(false);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setFilters((current) => (current.q === searchText.trim() ? current : { ...current, q: searchText.trim() }));
      if (typed.current) {
        typed.current = false;
        setPage(1);
      }
    }, 350);
    return () => window.clearTimeout(timer);
  }, [searchText]);

  const params = useMemo(() => filtersToParams(filters), [filters]);

  // Keep the URL in sync so views can be bookmarked and shared.
  useEffect(() => {
    const extra: Record<string, string> = {};
    if (page > 1) extra.page = String(page);
    if (pageSize !== 25) extra.page_size = String(pageSize);
    window.history.replaceState(null, "", `${window.location.pathname}${query({ ...params, ...extra })}${window.location.hash}`);
  }, [params, page, pageSize]);

  const loadFacets = useCallback(() => {
    api<Facets>("companies/facets").then(setFacets).catch(() => undefined);
  }, []);
  useEffect(() => loadFacets(), [loadFacets]);

  const path = useMemo(() => `companies${query({ ...params, page, page_size: pageSize })}`, [params, page, pageSize]);
  const requestKey = `${path}#${reloadKey}`;
  const loading = settledKey !== requestKey;

  useEffect(() => {
    let cancelled = false;
    api<CompanyPage>(path)
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setError("");
        setSettledKey(requestKey);
        if (result.page > result.pages && result.total > 0) setPage(result.pages);
      })
      .catch((reason) => {
        if (cancelled) return;
        setError(reason instanceof Error ? reason.message : "Could not load companies");
        setSettledKey(requestKey);
      });
    return () => {
      cancelled = true;
    };
  }, [path, requestKey]);

  const updateFilters = useCallback((patch: Partial<Filters>) => {
    setFilters((current) => ({ ...current, ...patch }));
    setPage(1);
    if ("q" in patch) setSearchText(patch.q || "");
  }, []);

  const onRowChange = useCallback((id: string, patch: Partial<CompanyRow>) => {
    setData((current) => current && { ...current, companies: current.companies.map((row) => (row.id === id ? { ...row, ...patch } : row)) });
  }, []);

  const onDataChanged = useCallback(() => {
    setReloadKey((value) => value + 1);
    loadFacets();
  }, [loadFacets]);

  async function setViewed(row: CompanyRow, viewed: boolean) {
    onRowChange(row.id, { viewed });
    try {
      const result = await api<{ viewed: boolean; viewed_at: string | null }>(`companies/${row.id}/view`, { method: "PUT", json: { viewed } });
      onRowChange(row.id, result);
    } catch (reason) {
      onRowChange(row.id, { viewed: !viewed });
      notify(reason instanceof Error ? reason.message : "Could not update viewed status", "error");
    }
  }

  async function markPageViewed() {
    const ids = (data?.companies || []).filter((row) => !row.viewed).map((row) => row.id);
    if (!ids.length) return;
    try {
      await api("companies/views", { method: "POST", json: { ids, viewed: true } });
      setData((current) => current && { ...current, companies: current.companies.map((row) => (ids.includes(row.id) ? { ...row, viewed: true } : row)) });
      notify(`Marked ${ids.length} companies as viewed`, "success");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Could not update viewed status", "error");
    }
  }

  function toggleQuick(quick: (typeof QUICK_FILTERS)[number]) {
    if (quick.active(filters)) {
      const reset: Partial<Filters> = {};
      for (const key of Object.keys(quick.apply) as Array<keyof Filters>) (reset as Record<string, unknown>)[key] = EMPTY_FILTERS[key];
      updateFilters(reset);
    } else {
      updateFilters(quick.apply);
    }
  }

  function sortBy(column: keyof typeof SORTABLE) {
    const option = SORTABLE[column];
    const next = filters.sort === option.desc && option.asc && option.asc !== option.desc ? option.asc : option.desc;
    updateFilters({ sort: next });
  }

  function sortIcon(column: keyof typeof SORTABLE) {
    const option = SORTABLE[column];
    if (filters.sort === option.desc) return column === "name" ? <ArrowUp size={12} /> : <ArrowDown size={12} />;
    if (option.asc && filters.sort === option.asc) return <ArrowUp size={12} />;
    return null;
  }

  const chips = useMemo(() => {
    const result: Array<{ key: string; text: string; remove: () => void }> = [];
    for (const key of ARRAY_KEYS) {
      for (const value of filters[key]) {
        result.push({ key: `${key}:${value}`, text: arrayChipLabel(key, value), remove: () => updateFilters({ [key]: filters[key].filter((item) => item !== value) } as Partial<Filters>) });
      }
    }
    for (const [key, format] of Object.entries(SCALAR_LABELS) as Array<[keyof Filters, (value: string) => string]>) {
      const value = filters[key] as string;
      if (value) result.push({ key, text: format(value), remove: () => updateFilters({ [key]: "" } as Partial<Filters>) });
    }
    return result;
  }, [filters, updateFilters]);

  const activeCount = activeFilterCount(filters);
  const rows = data?.companies || [];
  const unviewedOnPage = rows.filter((row) => !row.viewed).length;
  const firstRow = data && data.total ? (data.page - 1) * data.page_size + 1 : 0;
  const lastRow = data ? Math.min(data.total, data.page * data.page_size) : 0;
  const exportHref = `/api/backend/companies/export${query(params)}`;

  return (
    <section className="content-wrap">
      <div className="page-heading">
        <div>
          <h2>Companies</h2>
          <p>
            {data ? `${data.total.toLocaleString()} matching` : "Loading…"}
            {facets ? ` of ${facets.total.toLocaleString()} funded companies` : ""}
          </p>
        </div>
        <div className="heading-actions">
          <a className="button secondary" href={exportHref} download><Download size={15} /> Export CSV</a>
          {isAdmin && <button className="button primary" onClick={() => setAdding(true)}><Plus size={15} /> Add company</button>}
        </div>
      </div>

      <div className="toolbar">
        <label className="search-box">
          <Search size={17} />
          <input value={searchText} onChange={(event) => { typed.current = true; setSearchText(event.target.value); }} placeholder="Search name, description, domain, location, industry…" aria-label="Search companies" />
          {searchText && <button onClick={() => updateFilters({ q: "" })} aria-label="Clear search"><X size={15} /></button>}
        </label>
        <button className={`button secondary filter-toggle ${showFilters ? "active" : ""}`} onClick={() => setShowFilters((value) => !value)} aria-expanded={showFilters}>
          <SlidersHorizontal size={15} /> Filters {activeCount > 0 && <span className="count-badge">{activeCount}</span>}
        </button>
        <select className="native-select sort-select" value={filters.sort} onChange={(event) => updateFilters({ sort: event.target.value })} aria-label="Sort companies">
          {SORT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
        <button className="icon-button bordered" onClick={onDataChanged} disabled={loading} aria-label="Refresh"><RefreshCw size={16} className={loading ? "spin" : ""} /></button>
      </div>

      <div className="quick-filters" aria-label="Quick filters">
        {QUICK_FILTERS.map((quick) => (
          <button key={quick.label} className={`chip ${quick.active(filters) ? "active" : ""}`} onClick={() => toggleQuick(quick)} aria-pressed={quick.active(filters)}>
            {quick.label}
          </button>
        ))}
      </div>

      {showFilters && <FilterPanel filters={filters} facets={facets} onChange={updateFilters} />}

      {chips.length > 0 && (
        <div className="active-filters">
          {chips.map((chip) => (
            <span className="filter-chip" key={chip.key}>{chip.text}<button onClick={chip.remove} aria-label={`Remove ${chip.text}`}><X size={12} /></button></span>
          ))}
          <button className="link-button" onClick={() => updateFilters({ ...EMPTY_FILTERS, q: filters.q, sort: filters.sort })}>Clear all</button>
        </div>
      )}

      {error && (
        <div className="error-banner" role="alert">
          <div><strong>Companies could not be loaded</strong><p>{error}</p></div>
          <button onClick={onDataChanged}>Try again</button>
        </div>
      )}

      <div className="panel table-panel">
        <div className="table-scroll">
          <table className="company-table">
            <thead>
              <tr>
                <th className="col-viewed" title="Viewed">Viewed</th>
                <th><button className="th-sort" onClick={() => sortBy("name")}>Company {sortIcon("name")}</button></th>
                <th>Location</th>
                <th><button className="th-sort" onClick={() => sortBy("funded")}>Latest funding {sortIcon("funded")}</button></th>
                <th className="num"><button className="th-sort" onClick={() => sortBy("total")}>Total raised {sortIcon("total")}</button></th>
                <th><button className="th-sort" onClick={() => sortBy("founded")}>Founded {sortIcon("founded")}</button></th>
                <th>Website</th>
                <th><button className="th-sort" onClick={() => sortBy("jobs")}>Careers {sortIcon("jobs")}</button></th>
                <th className="col-note" title="My note"><StickyNote size={14} /></th>
              </tr>
            </thead>
            <tbody>
              {loading && !data && Array.from({ length: 8 }).map((_, index) => (
                <tr key={index} className="skeleton-row"><td colSpan={9}><span className="skeleton line-wide" /></td></tr>
              ))}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={9}><div className="empty-state"><Search size={28} /><strong>No companies match</strong><p>Try removing a filter or broadening your search.</p></div></td></tr>
              )}
              {rows.map((row) => {
                const website = safeHref(row.website);
                const careers = safeHref(row.careers_url);
                const estimated = row.founded_source ? ESTIMATED_FOUNDED.has(row.founded_source) : false;
                return (
                  <tr key={row.id} className={`${row.viewed ? "viewed" : "unviewed"} ${selectedId === row.id ? "selected" : ""}`} onClick={() => setSelectedId(row.id)}>
                    <td className="col-viewed" onClick={(event) => event.stopPropagation()}>
                      <label className="viewed-check" title={row.viewed ? "Viewed — uncheck to mark unviewed" : "Mark as viewed"}>
                        <input type="checkbox" checked={row.viewed} onChange={(event) => void setViewed(row, event.target.checked)} aria-label={`${row.name} viewed`} />
                        <span />
                      </label>
                    </td>
                    <td className="col-company">
                      <div className="company-cell">
                        <div className="company-logo">{initials(row.name)}</div>
                        <div>
                          <button className="company-name" onClick={(event) => { event.stopPropagation(); setSelectedId(row.id); }}>
                            {!row.viewed && <span className="unviewed-dot" aria-hidden />}{row.name}
                          </button>
                          <span className="company-sub">
                            {row.industry && <span className="industry">{row.industry}{row.stage ? ` · ${row.stage}` : ""} · </span>}
                            {row.description || row.subindustry || label(KIND_LABELS, row.entity_kind)}
                          </span>
                        </div>
                      </div>
                    </td>
                    <td><span className="cell-main">{[row.city, row.state].filter(Boolean).join(", ") || row.location || "—"}</span><span className="cell-sub">{row.country || ""}{row.is_remote ? " · Remote" : ""}</span></td>
                    <td><span className="cell-main" title={row.latest_round_type || undefined}>{roundLabel(row.latest_round_type)}</span><span className="cell-sub">{row.latest_round_on ? `${money(row.latest_amount_usd)} · ${shortDate(row.latest_round_on)}` : ""}</span></td>
                    <td className="num"><span className="cell-money">{money(row.total_funding_usd)}</span></td>
                    <td title={row.founded_source ? label(FOUNDED_SOURCE_LABELS, row.founded_source) : undefined}>
                      {row.founded_year ? <span className={estimated ? "estimated" : ""}>{estimated ? "~" : ""}{row.founded_year}</span> : <span className="muted">—</span>}
                    </td>
                    <td onClick={(event) => event.stopPropagation()}>
                      {website ? (
                        <a className="link-pill" href={website} target="_blank" rel="noreferrer" title={row.website_status === "verified" ? "Verified website" : "Website (not verified)"}>
                          {hostname(row.website)} <ExternalLink size={11} />
                        </a>
                      ) : <span className="muted">None</span>}
                    </td>
                    <td onClick={(event) => event.stopPropagation()}>
                      {row.has_careers_page ? (
                        careers ? (
                          <a className="badge success" href={careers} target="_blank" rel="noreferrer" title={label(PROVIDER_LABELS, row.careers_provider)}>
                            <Briefcase size={12} /> {row.open_jobs_count !== null ? `${row.open_jobs_count} job${row.open_jobs_count === 1 ? "" : "s"}` : "Careers"}
                          </a>
                        ) : <span className="badge success"><Briefcase size={12} /> Careers</span>
                      ) : row.careers_checked_at ? <span className="badge muted-badge">None</span> : <span className="muted">Not checked</span>}
                    </td>
                    <td className="col-note">{row.note ? <span title={row.note}><StickyNote size={15} className="note-icon" /></span> : null}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="pagination">
          <span>{data && data.total ? `${firstRow.toLocaleString()}–${lastRow.toLocaleString()} of ${data.total.toLocaleString()}` : "No results"}</span>
          <div className="pagination-actions">
            {unviewedOnPage > 0 && (
              <button className="button secondary small" onClick={() => void markPageViewed()}><CheckCheck size={14} /> Mark page viewed</button>
            )}
            <select className="native-select small" value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1); }} aria-label="Rows per page">
              {PAGE_SIZES.map((size) => <option key={size} value={size}>{size} / page</option>)}
            </select>
            <button className="icon-button bordered" disabled={page <= 1 || loading} onClick={() => setPage((value) => value - 1)} aria-label="Previous page"><ChevronLeft size={17} /></button>
            <span className="page-indicator">Page {data?.page || page} of {data?.pages || 1}</span>
            <button className="icon-button bordered" disabled={!data || page >= data.pages || loading} onClick={() => setPage((value) => value + 1)} aria-label="Next page"><ChevronRight size={17} /></button>
          </div>
        </div>
      </div>

      {selectedId && (
        <CompanyDrawer
          key={selectedId}
          companyId={selectedId}
          isAdmin={isAdmin}
          onClose={() => setSelectedId(null)}
          onRowChange={onRowChange}
          onDataChanged={onDataChanged}
          notify={notify}
        />
      )}
      {adding && (
        <CompanyForm
          onClose={() => setAdding(false)}
          onSaved={(company: CompanyDetail) => {
            setAdding(false);
            notify(`${company.name} added`, "success");
            onDataChanged();
            setSelectedId(company.id);
          }}
        />
      )}
    </section>
  );
}
