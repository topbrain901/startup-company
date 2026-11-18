"use client";

import { RotateCcw } from "lucide-react";
import { useMemo } from "react";
import { KIND_LABELS, PROVIDER_LABELS, label } from "../../lib/format";
import {
  ADDED_WITHIN_OPTIONS,
  AMOUNT_OPTIONS,
  EMPTY_FILTERS,
  FUNDED_WITHIN_OPTIONS,
  type Filters,
} from "../../lib/filters";
import type { Facets } from "../../lib/types";
import { MultiSelect, NumberRange, Segmented, SelectField } from "./controls";

const ANY_YES_NO = (yes: string, no: string) => [
  { value: "" as const, label: "Any" },
  { value: "yes" as const, label: yes },
  { value: "no" as const, label: no },
];

export default function FilterPanel({
  filters,
  facets,
  onChange,
}: {
  filters: Filters;
  facets: Facets | null;
  onChange: (patch: Partial<Filters>) => void;
}) {
  const states = useMemo(() => {
    const all = facets?.states || [];
    const scoped = filters.country.length ? all.filter((item) => item.country && filters.country.includes(item.country)) : all;
    const merged = new Map<string, number>();
    for (const item of scoped) merged.set(item.value, (merged.get(item.value) || 0) + item.count);
    return [...merged.entries()].map(([value, count]) => ({ value, count })).sort((a, b) => b.count - a.count);
  }, [facets, filters.country]);

  const kindLabel = (value: string) => label(KIND_LABELS, value);
  const providerLabel = (value: string) => label(PROVIDER_LABELS, value);

  return (
    <div className="filter-panel">
      <section className="filter-group">
        <h4>Location</h4>
        <div className="filter-grid">
          <MultiSelect
            label="Country"
            options={facets?.countries || []}
            value={filters.country}
            onChange={(country) => {
              const allowed = new Set(
                (facets?.states || [])
                  .filter((item) => !country.length || (item.country && country.includes(item.country)))
                  .map((item) => item.value),
              );
              onChange({ country, state: filters.state.filter((item) => allowed.has(item)) });
            }}
          />
          <MultiSelect label="State / region" options={states} value={filters.state} onChange={(state) => onChange({ state })} />
          <label className="field">
            <span className="field-label">City or place contains</span>
            <input className="text-input" value={filters.location} onChange={(event) => onChange({ location: event.target.value })} placeholder="e.g. Austin, London, Bay Area" />
          </label>
          <Segmented label="Remote" value={filters.remote} options={ANY_YES_NO("Remote", "On-site")} onChange={(remote) => onChange({ remote })} />
        </div>
      </section>

      <section className="filter-group">
        <h4>Website & careers</h4>
        <div className="filter-grid">
          <Segmented label="Own website" value={filters.website} options={ANY_YES_NO("Has site", "No site")} onChange={(website) => onChange({ website })} />
          <Segmented
            label="Careers page"
            value={filters.careers}
            options={[
              { value: "", label: "Any" },
              { value: "yes", label: "Yes" },
              { value: "no", label: "No" },
              { value: "unchecked", label: "Unchecked" },
            ]}
            onChange={(careers) => onChange({ careers })}
          />
          <MultiSelect label="Jobs hosted on" options={facets?.providers || []} value={filters.provider} onChange={(provider) => onChange({ provider })} formatOption={providerLabel} />
          <Segmented label="Hiring" value={filters.hiring} options={ANY_YES_NO("Hiring", "Not hiring")} onChange={(hiring) => onChange({ hiring })} />
          <label className="field">
            <span className="field-label">Minimum open jobs</span>
            <input className="text-input" type="number" min={0} value={filters.min_jobs} onChange={(event) => onChange({ min_jobs: event.target.value })} placeholder="e.g. 3" />
          </label>
        </div>
      </section>

      <section className="filter-group">
        <h4>Funding</h4>
        <div className="filter-grid">
          <MultiSelect label="Round type" options={facets?.round_types || []} value={filters.round_type} onChange={(round_type) => onChange({ round_type })} />
          <SelectField label="Last funded" value={filters.funded_within} options={FUNDED_WITHIN_OPTIONS} onChange={(funded_within) => onChange({ funded_within })} />
          <SelectField label="Latest round at least" value={filters.amount_min} options={AMOUNT_OPTIONS} onChange={(amount_min) => onChange({ amount_min })} />
          <SelectField label="Latest round at most" value={filters.amount_max} options={AMOUNT_OPTIONS} onChange={(amount_max) => onChange({ amount_max })} />
          <SelectField label="Total raised at least" value={filters.total_min} options={AMOUNT_OPTIONS} onChange={(total_min) => onChange({ total_min })} />
        </div>
      </section>

      <section className="filter-group">
        <h4>Company</h4>
        <div className="filter-grid">
          <MultiSelect label="Industry" options={facets?.industries || []} value={filters.industry} onChange={(industry) => onChange({ industry })} />
          <MultiSelect label="Company type" options={facets?.kinds || []} value={filters.kind} onChange={(kind) => onChange({ kind })} formatOption={kindLabel} />
          <NumberRange
            label={`Founded year${facets?.founded_min ? ` (${facets.founded_min}–${facets.founded_max})` : ""}`}
            from={filters.founded_from}
            to={filters.founded_to}
            min={1800}
            max={2100}
            onChange={(founded_from, founded_to) => onChange({ founded_from, founded_to })}
          />
          <Segmented label="Founding date" value={filters.founded_known} options={ANY_YES_NO("Known", "Unknown")} onChange={(founded_known) => onChange({ founded_known })} />
          <NumberRange label="Team size" from={filters.team_min} to={filters.team_max} min={0} placeholderFrom="Min" placeholderTo="Max" onChange={(team_min, team_max) => onChange({ team_min, team_max })} />
          <MultiSelect label="Stage" options={facets?.stages || []} value={filters.stage} onChange={(stage) => onChange({ stage })} />
          <MultiSelect label="Status" options={facets?.statuses || []} value={filters.status} onChange={(status) => onChange({ status })} />
          <MultiSelect label="YC batch" options={facets?.batches || []} value={filters.batch} onChange={(batch) => onChange({ batch })} />
          <MultiSelect label="Data source" options={facets?.sources || []} value={filters.source} onChange={(source) => onChange({ source })} />
          <SelectField label="Added to database" value={filters.added_within} options={ADDED_WITHIN_OPTIONS} onChange={(added_within) => onChange({ added_within })} />
        </div>
      </section>

      <section className="filter-group">
        <h4>My tracking</h4>
        <div className="filter-grid">
          <Segmented label="Viewed" value={filters.viewed} options={ANY_YES_NO("Viewed", "Unviewed")} onChange={(viewed) => onChange({ viewed })} />
          <Segmented label="My notes" value={filters.notes} options={ANY_YES_NO("Has note", "No note")} onChange={(notes) => onChange({ notes })} />
        </div>
      </section>

      <div className="filter-panel-footer">
        <button className="button secondary small" onClick={() => onChange({ ...EMPTY_FILTERS, q: filters.q, sort: filters.sort })}>
          <RotateCcw size={14} /> Reset filters
        </button>
      </div>
    </div>
  );
}
