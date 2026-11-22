"use client";

import { CircleAlert, Database, Loader2, Play, RefreshCw, Square, Undo2, WandSparkles } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { duration, percent, relativeTime, shortDate } from "../../lib/format";
import type { Coverage, Job, Tombstone } from "../../lib/types";
import { Modal } from "./controls";

type Notify = (message: string, tone?: "info" | "error" | "success") => void;

const ENRICH_TARGETS = [
  { value: "missing_website", label: "Companies without a website", hint: "Finds websites, then checks careers pages and founding dates." },
  { value: "never", label: "Never enriched", hint: "Companies that have not been checked yet." },
  { value: "careers_unchecked", label: "Website known, careers not checked", hint: "Fastest way to mark careers pages." },
  { value: "missing_founded", label: "Missing or estimated founding date", hint: "Looks up YC profiles, Wikidata, and the website." },
  { value: "missing_contacts", label: "Website known, no LinkedIn / X / email", hint: "Reads social profiles and a contact email from the site, YC, and Wikidata." },
  { value: "stale", label: "Enriched more than 30 days ago", hint: "Refreshes careers pages and open-job counts." },
  { value: "all", label: "All companies", hint: "Least recently enriched first." },
];
const SOURCES = [
  { value: "sec", label: "SEC Form D filings", hint: "US exempt offerings, quarterly bulk data" },
  { value: "rss", label: "Funding news (RSS)", hint: "TechCrunch, Crunchbase News, EU-Startups, Tech.eu, VentureBeat" },
  { value: "yc", label: "Y Combinator directory", hint: "All public YC companies" },
  { value: "fundingwatcher", label: "FundingWatcher", hint: "Recently funded list + one page per round stage (~300 companies)" },
  { value: "producthunt", label: "Product Hunt", hint: "New product launches from the official Atom feed" },
  { value: "betalist", label: "BetaList", hint: "Upcoming startups and early-access products" },
  { value: "antler", label: "Antler portfolio", hint: "Public inception-stage investor portfolio" },
  { value: "ef", label: "Entrepreneur First", hint: "Public talent-investor portfolio" },
  { value: "techstars", label: "Techstars portfolio", hint: "Public accelerator portfolio companies" },
  { value: "wellfound", label: "Wellfound", hint: "Public startup discovery directory" },
];
const EARLY_STAGE_TYPES = [
  { value: "pre-seed", label: "Pre-seed", hint: "Includes explicit pre-seed, angel, and friends-and-family rounds." },
  { value: "bootstrapped", label: "Bootstrapped", hint: "Companies explicitly described as bootstrapped." },
  { value: "pre-funding", label: "Pre-funding", hint: "Unfunded companies or companies with no outside capital yet." },
  { value: "ideation", label: "Ideation", hint: "Idea-stage or concept-stage companies." },
  { value: "self-funded", label: "Self-funded", hint: "Founder-funded or explicitly self-funded companies." },
];
const STATUS_LABEL: Record<string, string> = { queued: "Queued", running: "Running", completed: "Completed", failed: "Failed", cancelled: "Cancelled" };

export default function ScraperView({ notify }: { notify: Notify }) {
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [active, setActive] = useState<Job | null>(null);
  const [history, setHistory] = useState<Job[]>([]);
  const [deleted, setDeleted] = useState<Tombstone[]>([]);
  const [starting, setStarting] = useState<"" | "collect" | "enrich">("");
  const [detail, setDetail] = useState<Job | null>(null);
  const [collect, setCollect] = useState({ sources: SOURCES.filter((source) => source.value !== "sec").map((source) => source.value), funding_types: [] as string[], sec_quarters: 1, limit: "", include_funds: false, enrich_after: true, enrich_limit: 200 });
  const [enrich, setEnrich] = useState({ target: "missing_website", limit: 500, only_startups: true });

  const refresh = useCallback(async () => {
    const [stats, current, runs, tombstones] = await Promise.allSettled([
      api<Coverage>("admin/stats"),
      api<Job | null>("admin/jobs/active"),
      api<Job[]>("admin/jobs"),
      api<Tombstone[]>("admin/deleted-companies"),
    ]);
    if (stats.status === "fulfilled") setCoverage(stats.value);
    if (current.status === "fulfilled") setActive(current.value);
    if (runs.status === "fulfilled") setHistory(runs.value);
    if (tombstones.status === "fulfilled") setDeleted(tombstones.value);
    const failure = [stats, current, runs].find((item) => item.status === "rejected") as PromiseRejectedResult | undefined;
    if (failure) notify(failure.reason instanceof Error ? failure.reason.message : "Could not load scraper status", "error");
  }, [notify]);

  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  // Poll quickly while a job runs, slowly otherwise.
  useEffect(() => {
    const running = active && (active.status === "running" || active.status === "queued");
    const timer = window.setInterval(async () => {
      if (running) {
        try {
          const current = await api<Job | null>("admin/jobs/active");
          setActive(current);
          if (!current) void refresh();
        } catch {
          /* transient; next tick retries */
        }
      } else {
        void refresh();
      }
    }, running ? 2500 : 20000);
    return () => window.clearInterval(timer);
  }, [active, refresh]);

  async function start(kind: "collect" | "enrich") {
    setStarting(kind);
    try {
      const body = kind === "collect"
        ? { ...collect, limit: collect.limit ? Number(collect.limit) : null, enrich_limit: collect.enrich_after ? collect.enrich_limit : 0 }
        : enrich;
      const job = await api<Job>(`admin/jobs/${kind}`, { method: "POST", json: body });
      setActive(job);
      notify(kind === "collect" ? "Scrape started" : "Enrichment started", "success");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Could not start job", "error");
    } finally {
      setStarting("");
    }
  }

  async function cancel() {
    if (!active) return;
    try {
      await api(`admin/jobs/${active.id}/cancel`, { method: "POST" });
      notify("Cancelling… companies already in progress will finish first.", "info");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Could not cancel", "error");
    }
  }

  async function openRun(run: Job) {
    try {
      setDetail(await api<Job>(`admin/jobs/${run.id}`));
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Could not load run", "error");
    }
  }

  async function restore(item: Tombstone) {
    try {
      await api("admin/deleted-companies/restore", { method: "POST", json: { source_key: item.source_key } });
      setDeleted((current) => current.filter((entry) => entry.source_key !== item.source_key));
      notify(`${item.name || "Company"} will be re-imported by the next scrape`, "success");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Could not restore", "error");
    }
  }

  const running = !!active && (active.status === "running" || active.status === "queued");
  const total = active?.progress?.total || 0;
  const processed = active?.progress?.processed || 0;

  return (
    <section className="content-wrap">
      <div className="page-heading">
        <div><h2>Scraper</h2><p>Collect funded companies and enrich them with websites, careers pages, and founding dates.</p></div>
        <div className="heading-actions"><button className="button secondary" onClick={() => void refresh()}><RefreshCw size={15} /> Refresh</button></div>
      </div>

      {coverage && (
        <div className="coverage-grid">
          <CoverageCard label="Companies" value={coverage.total.toLocaleString()} note={`${coverage.startups.toLocaleString()} startups / operating companies`} />
          <CoverageCard label="With website" value={percent(coverage.with_website, coverage.total)} note={`${coverage.with_website.toLocaleString()} · ${coverage.website_verified.toLocaleString()} verified`} ratio={coverage.with_website / Math.max(1, coverage.total)} />
          <CoverageCard label="Careers page found" value={coverage.with_careers.toLocaleString()} note={`${coverage.careers_checked.toLocaleString()} checked · ${coverage.hiring.toLocaleString()} hiring`} ratio={coverage.careers_checked / Math.max(1, coverage.total)} />
          <CoverageCard label="Founding date" value={percent(coverage.founded_known, coverage.total)} note={`${coverage.founded_estimated.toLocaleString()} are estimates`} ratio={coverage.founded_known / Math.max(1, coverage.total)} />
          {coverage.with_social !== undefined && (
            <CoverageCard label="Profiles & email" value={percent(coverage.with_social, coverage.total)} note={`${(coverage.with_linkedin || 0).toLocaleString()} LinkedIn · ${(coverage.with_contact_email || 0).toLocaleString()} contact emails`} ratio={coverage.with_social / Math.max(1, coverage.total)} />
          )}
          <CoverageCard label="Not enriched yet" value={coverage.never_enriched.toLocaleString()} note={`${coverage.website_not_found.toLocaleString()} searched, no site found`} />
        </div>
      )}

      {active && (
        <div className={`panel job-panel ${running ? "running" : ""}`}>
          <div className="job-head">
            <div>
              <p className="eyebrow">{active.kind === "collect" ? "SCRAPE JOB" : "ENRICHMENT JOB"}</p>
              <h3>{running ? <Loader2 size={17} className="spin" /> : null} {STATUS_LABEL[active.status]} · {active.progress?.stage || "starting"}</h3>
              <span className="muted small-text">Started {relativeTime(active.started_at)} · {duration(active.started_at, null)}</span>
            </div>
            {running && <button className="button danger-outline" onClick={() => void cancel()}><Square size={14} /> Cancel</button>}
          </div>
          {total > 0 && (
            <div className="progress">
              <div className="progress-bar"><span style={{ width: `${Math.min(100, (processed / total) * 100)}%` }} /></div>
              <span>{processed.toLocaleString()} / {total.toLocaleString()}</span>
            </div>
          )}
          <div className="job-counters">
            {active.kind === "collect" && <span><strong>{active.companies_saved.toLocaleString()}</strong> companies saved</span>}
            {active.kind === "collect" && <span><strong>{active.rounds_saved.toLocaleString()}</strong> rounds saved</span>}
            <span><strong>{active.websites_found.toLocaleString()}</strong> websites found</span>
            <span><strong>{active.careers_found.toLocaleString()}</strong> careers pages</span>
            <span><strong>{active.founded_found.toLocaleString()}</strong> founding dates</span>
            {active.contacts_found !== undefined && <span><strong>{active.contacts_found.toLocaleString()}</strong> with new links</span>}
            {(active.progress?.errors || 0) > 0 && <span><strong>{active.progress.errors}</strong> errors</span>}
          </div>
          {active.log && active.log.length > 0 && <pre className="job-log">{active.log.slice(-14).join("\n")}</pre>}
        </div>
      )}

      <div className="launch-grid">
        <div className="panel launch-card">
          <div className="launch-head"><Database size={18} /><div><h3>Collect new data</h3><p>Pull the latest companies and funding rounds from public sources.</p></div></div>
          <div className="check-list">
            {SOURCES.map((source) => (
              <label key={source.value} className="check-row">
                <input
                  type="checkbox"
                  checked={collect.sources.includes(source.value)}
                  onChange={(event) => setCollect({ ...collect, sources: event.target.checked ? [...collect.sources, source.value] : collect.sources.filter((item) => item !== source.value) })}
                />
                <span><strong>{source.label}</strong><small>{source.hint}</small></span>
              </label>
            ))}
          </div>
          <div className="stage-filter-box">
            <div className="stage-filter-heading">
              <div><strong>Funding / company stage</strong><small>Leave all unchecked to collect every stage. Selected runs keep only explicit matches.</small></div>
              {collect.funding_types.length > 0 && <button type="button" className="text-button" onClick={() => setCollect({ ...collect, funding_types: [] })}>Clear</button>}
            </div>
            <div className="stage-chip-grid">
              {EARLY_STAGE_TYPES.map((stage) => (
                <label key={stage.value} className={`stage-chip ${collect.funding_types.includes(stage.value) ? "selected" : ""}`} title={stage.hint}>
                  <input
                    type="checkbox"
                    checked={collect.funding_types.includes(stage.value)}
                    onChange={(event) => setCollect({
                      ...collect,
                      funding_types: event.target.checked
                        ? [...collect.funding_types, stage.value]
                        : collect.funding_types.filter((item) => item !== stage.value),
                    })}
                  />
                  <span>{stage.label}</span>
                </label>
              ))}
            </div>
            {collect.funding_types.length > 0 && <p className="stage-warning"><CircleAlert size={14} /> SEC Form D does not identify pre-seed or self-funded stages, so unknown SEC rounds are excluded.</p>}
          </div>
          <div className="form-grid compact">
            <label className="field"><span className="field-label">SEC quarters</span><input className="text-input" type="number" min={1} max={40} value={collect.sec_quarters} onChange={(event) => setCollect({ ...collect, sec_quarters: Math.max(1, Number(event.target.value) || 1) })} /></label>
            <label className="field"><span className="field-label">Max records per source</span><input className="text-input" type="number" min={1} placeholder="No limit" value={collect.limit} onChange={(event) => setCollect({ ...collect, limit: event.target.value })} /></label>
            <label className="check-row span-2"><input type="checkbox" checked={collect.include_funds} onChange={(event) => setCollect({ ...collect, include_funds: event.target.checked })} /><span><strong>Include pooled investment funds</strong><small>Usually not useful for finding operating startups.</small></span></label>
            <label className="check-row span-2"><input type="checkbox" checked={collect.enrich_after} onChange={(event) => setCollect({ ...collect, enrich_after: event.target.checked })} /><span><strong>Enrich new companies afterwards</strong><small>Website, careers page, and founding date for never-checked startups.</small></span></label>
            {collect.enrich_after && <label className="field"><span className="field-label">Companies to enrich</span><input className="text-input" type="number" min={1} max={20000} value={collect.enrich_limit} onChange={(event) => setCollect({ ...collect, enrich_limit: Math.max(1, Number(event.target.value) || 1) })} /></label>}
          </div>
          <button className="button primary wide" disabled={running || starting !== "" || collect.sources.length === 0} onClick={() => void start("collect")}>
            {starting === "collect" ? <Loader2 size={15} className="spin" /> : <Play size={15} />} Start scrape
          </button>
        </div>

        <div className="panel launch-card">
          <div className="launch-head"><WandSparkles size={18} /><div><h3>Enrich existing companies</h3><p>Find official websites, careers pages, open jobs, and founding dates. No API keys needed.</p></div></div>
          <div className="check-list">
            {ENRICH_TARGETS.map((target) => (
              <label key={target.value} className="check-row">
                <input type="radio" name="enrich-target" checked={enrich.target === target.value} onChange={() => setEnrich({ ...enrich, target: target.value })} />
                <span><strong>{target.label}</strong><small>{target.hint}</small></span>
              </label>
            ))}
          </div>
          <div className="form-grid compact">
            <label className="field"><span className="field-label">Maximum companies</span><input className="text-input" type="number" min={1} max={20000} value={enrich.limit} onChange={(event) => setEnrich({ ...enrich, limit: Math.max(1, Number(event.target.value) || 1) })} /></label>
            <label className="check-row"><input type="checkbox" checked={enrich.only_startups} onChange={(event) => setEnrich({ ...enrich, only_startups: event.target.checked })} /><span><strong>Startups only</strong><small>Skip funds, SPVs, and real estate.</small></span></label>
          </div>
          <p className="muted small-text">Roughly 5–20 seconds per company with 6 parallel workers. Results are saved as each company finishes.</p>
          <button className="button primary wide" disabled={running || starting !== ""} onClick={() => void start("enrich")}>
            {starting === "enrich" ? <Loader2 size={15} className="spin" /> : <WandSparkles size={15} />} Start enrichment
          </button>
        </div>
      </div>

      <div className="panel">
        <div className="panel-heading"><div><p className="eyebrow">HISTORY</p><h3>Recent runs</h3></div></div>
        <div className="table-scroll">
          <table className="simple-table">
            <thead><tr><th>Started</th><th>Type</th><th>Status</th><th className="num">Companies</th><th className="num">Rounds</th><th className="num">Enriched</th><th className="num">Websites</th><th className="num">Careers</th><th>Duration</th><th>By</th></tr></thead>
            <tbody>
              {history.length === 0 && <tr><td colSpan={10} className="muted">No runs yet.</td></tr>}
              {history.map((run) => (
                <tr key={run.id} className="clickable" onClick={() => void openRun(run)}>
                  <td>{shortDate(run.created_at)} <span className="muted">{run.created_at ? new Date(run.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : ""}</span></td>
                  <td>{run.kind === "collect" ? `Scrape (${(run.sources || []).join(", ")})` : "Enrichment"}</td>
                  <td><span className={`status-pill ${run.status}`}>{STATUS_LABEL[run.status]}</span>{run.error && <span title={run.error}><CircleAlert size={13} className="error-icon" /></span>}</td>
                  <td className="num">{run.companies_saved.toLocaleString()}</td>
                  <td className="num">{run.rounds_saved.toLocaleString()}</td>
                  <td className="num">{run.enriched_count.toLocaleString()}</td>
                  <td className="num">{run.websites_found.toLocaleString()}</td>
                  <td className="num">{run.careers_found.toLocaleString()}</td>
                  <td>{duration(run.started_at, run.completed_at)}</td>
                  <td className="muted">{run.requested_by_email || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {deleted.length > 0 && (
        <div className="panel">
          <div className="panel-heading"><div><p className="eyebrow">DELETED</p><h3>Deleted companies ({deleted.length})</h3><p className="muted small-text">Scrapes skip these. Restore one to let the next scrape import it again.</p></div></div>
          <div className="table-scroll">
            <table className="simple-table">
              <thead><tr><th>Company</th><th>Source</th><th>Deleted</th><th>By</th><th /></tr></thead>
              <tbody>
                {deleted.map((item) => (
                  <tr key={item.source_key}>
                    <td>{item.name || item.source_key}</td>
                    <td className="muted">{item.source_name || "—"}</td>
                    <td>{shortDate(item.deleted_at)}</td>
                    <td className="muted">{item.deleted_by || "—"}</td>
                    <td className="num"><button className="button secondary small" onClick={() => void restore(item)}><Undo2 size={13} /> Restore</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {detail && (
        <Modal title={`${detail.kind === "collect" ? "Scrape" : "Enrichment"} run · ${STATUS_LABEL[detail.status]}`} onClose={() => setDetail(null)} wide>
          <div className="modal-body">
            <dl className="detail-grid">
              <div><dt>Started</dt><dd>{shortDate(detail.started_at)} {detail.started_at ? new Date(detail.started_at).toLocaleTimeString() : ""}</dd></div>
              <div><dt>Duration</dt><dd>{duration(detail.started_at, detail.completed_at)}</dd></div>
              <div><dt>Companies found / saved</dt><dd>{detail.companies_found.toLocaleString()} / {detail.companies_saved.toLocaleString()}</dd></div>
              <div><dt>Rounds found / saved</dt><dd>{detail.rounds_found.toLocaleString()} / {detail.rounds_saved.toLocaleString()}</dd></div>
              <div><dt>Enriched</dt><dd>{detail.enriched_count.toLocaleString()}</dd></div>
              <div><dt>Found</dt><dd>{detail.websites_found} websites · {detail.careers_found} careers · {detail.founded_found} founding dates{detail.contacts_found !== undefined ? ` · ${detail.contacts_found} with new links` : ""}</dd></div>
            </dl>
            {detail.error && <p className="form-error">{detail.error}</p>}
            <p className="field-label">Options</p>
            <pre className="job-log small">{JSON.stringify(detail.options, null, 2)}</pre>
            <p className="field-label">Log</p>
            <pre className="job-log">{(detail.log || []).join("\n") || "No log lines."}</pre>
          </div>
        </Modal>
      )}
    </section>
  );
}

function CoverageCard({ label, value, note, ratio }: { label: string; value: string; note: string; ratio?: number }) {
  return (
    <article className="coverage-card">
      <p>{label}</p>
      <strong>{value}</strong>
      {ratio !== undefined && <div className="mini-bar"><span style={{ width: `${Math.round(Math.min(1, ratio) * 100)}%` }} /></div>}
      <small>{note}</small>
    </article>
  );
}
