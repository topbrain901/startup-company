"use client";

import {
  Briefcase,
  Check,
  ExternalLink,
  Globe,
  Loader2,
  LockOpen,
  Mail,
  Pencil,
  Plus,
  Trash2,
  WandSparkles,
  X,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";
import {
  DISCOVERY_LABELS,
  ESTIMATED_FOUNDED,
  FOUNDED_SOURCE_LABELS,
  KIND_LABELS,
  PROVIDER_LABELS,
  WEBSITE_STATUS_LABELS,
  hostname,
  initials,
  label,
  money,
  profileHandle,
  relativeTime,
  safeHref,
  safeMailto,
  shortDate,
} from "../../lib/format";
import type { CompanyDetail, CompanyRow, FundingRound } from "../../lib/types";
import CompanyForm from "./company-form";
import { ConfirmDialog, Modal } from "./controls";

type NoteState = "idle" | "saving" | "saved" | "error";

export default function CompanyDrawer({
  companyId,
  isAdmin,
  onClose,
  onRowChange,
  onDataChanged,
  notify,
}: {
  companyId: string;
  isAdmin: boolean;
  onClose: () => void;
  onRowChange: (id: string, patch: Partial<CompanyRow>) => void;
  onDataChanged: () => void;
  notify: (message: string, tone?: "info" | "error" | "success") => void;
}) {
  const [company, setCompany] = useState<CompanyDetail | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [noteState, setNoteState] = useState<NoteState>("idle");
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState<"" | "enrich" | "delete" | "unlock">("");
  const [enrichLog, setEnrichLog] = useState<string[] | null>(null);
  const [roundEditor, setRoundEditor] = useState<FundingRound | "new" | null>(null);
  const pendingNote = useRef<string | null>(null);
  const noteTimer = useRef<number | undefined>(undefined);

  const applyDetail = useCallback((detail: CompanyDetail) => {
    setCompany(detail);
    setNote(detail.note || "");
  }, []);

  // Load the company and mark it viewed the first time it is opened. (The parent keys this
  // component by company id, so state starts fresh for every company.)
  useEffect(() => {
    let cancelled = false;
    api<CompanyDetail>(`companies/${companyId}`)
      .then(async (detail) => {
        if (cancelled) return;
        applyDetail(detail);
        if (!detail.viewed) {
          const result = await api<{ viewed: boolean; viewed_at: string | null }>(`companies/${companyId}/view`, { method: "PUT", json: { viewed: true } });
          if (cancelled) return;
          setCompany((current) => (current ? { ...current, ...result } : current));
          onRowChange(companyId, result);
        }
      })
      .catch((reason) => !cancelled && setError(reason instanceof Error ? reason.message : "Could not load company"));
    return () => {
      cancelled = true;
    };
  }, [companyId, applyDetail, onRowChange]);

  const saveNote = useCallback(async (value: string) => {
    pendingNote.current = null;
    setNoteState("saving");
    try {
      const result = await api<{ note: string; updated_at: string | null }>(`companies/${companyId}/note`, { method: "PUT", json: { note: value } });
      setNoteState("saved");
      onRowChange(companyId, { note: result.note || null, note_updated_at: result.updated_at });
    } catch (reason) {
      setNoteState("error");
      notify(reason instanceof Error ? reason.message : "Could not save note", "error");
    }
  }, [companyId, onRowChange, notify]);

  // Flush an unsaved note when the drawer closes.
  useEffect(() => () => {
    window.clearTimeout(noteTimer.current);
    if (pendingNote.current !== null) void saveNote(pendingNote.current);
  }, [saveNote]);

  function changeNote(value: string) {
    setNote(value);
    setNoteState("idle");
    pendingNote.current = value;
    window.clearTimeout(noteTimer.current);
    noteTimer.current = window.setTimeout(() => void saveNote(value), 900);
  }

  async function toggleViewed(viewed: boolean) {
    try {
      const result = await api<{ viewed: boolean; viewed_at: string | null }>(`companies/${companyId}/view`, { method: "PUT", json: { viewed } });
      setCompany((current) => (current ? { ...current, ...result } : current));
      onRowChange(companyId, result);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Could not update viewed status", "error");
    }
  }

  async function reEnrich() {
    setBusy("enrich");
    setEnrichLog(null);
    try {
      const result = await api<{ company: CompanyDetail; log: string[]; error: string | null }>(`admin/companies/${companyId}/enrich`, { method: "POST" });
      applyDetail(result.company);
      setEnrichLog(result.error ? [...result.log, `Error: ${result.error}`] : result.log.length ? result.log : ["No new information found."]);
      onDataChanged();
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Enrichment failed", "error");
    } finally {
      setBusy("");
    }
  }

  async function remove() {
    setBusy("delete");
    try {
      await api(`admin/companies/${companyId}`, { method: "DELETE" });
      notify("Company deleted. It will not be re-imported by future scrapes.", "success");
      onDataChanged();
      onClose();
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Could not delete company", "error");
      setBusy("");
      setConfirmDelete(false);
    }
  }

  async function unlock() {
    setBusy("unlock");
    try {
      applyDetail(await api<CompanyDetail>(`admin/companies/${companyId}/unlock`, { method: "POST" }));
      notify("Edited fields unlocked. Scrapes and enrichment may update them again.", "success");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Could not unlock fields", "error");
    } finally {
      setBusy("");
    }
  }

  async function deleteRound(round: FundingRound) {
    try {
      await api(`admin/funding-rounds/${round.id}`, { method: "DELETE" });
      applyDetail(await api<CompanyDetail>(`companies/${companyId}`));
      onDataChanged();
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Could not delete round", "error");
    }
  }

  const website = safeHref(company?.website);
  const careers = safeHref(company?.careers_url);
  const source = safeHref(company?.source_url);
  const email = safeMailto(company?.contact_email);
  const profiles = company
    ? ([
        ["LinkedIn", safeHref(company.linkedin_url), profileHandle(company.linkedin_url)],
        ["X", safeHref(company.twitter_url), profileHandle(company.twitter_url, "@")],
        ["GitHub", safeHref(company.github_url), profileHandle(company.github_url)],
      ] as const).filter(([, href]) => href)
    : [];
  const estimated = company?.founded_source ? ESTIMATED_FOUNDED.has(company.founded_source) : false;
  const edited = (company?.edited_fields || []).filter((field) => !["normalized_name", "domain", "founded_source", "founded_on", "website_status", "website_discovery_source", "website_verified_at", "careers_provider", "careers_checked_at"].includes(field));

  return (
    <div className="drawer-layer" role="dialog" aria-modal="true" aria-label={company ? `${company.name} details` : "Company details"}>
      <button className="drawer-backdrop" onClick={onClose} aria-label="Close details" />
      <aside className="detail-drawer">
        <button className="drawer-close" onClick={onClose} aria-label="Close details"><X size={19} /></button>
        {error && <div className="error-banner"><div><strong>Could not load company</strong><p>{error}</p></div></div>}
        {!company && !error && <div className="drawer-loading"><Loader2 className="spin" size={22} /> Loading company…</div>}
        {company && (
          <>
            <div className="drawer-head">
              <div className="detail-logo">{initials(company.name)}</div>
              <div>
                <p className="eyebrow">{label(KIND_LABELS, company.entity_kind).toUpperCase()}</p>
                <h2>{company.name}</h2>
                {website ? (
                  <a className="drawer-domain" href={website} target="_blank" rel="noreferrer">{hostname(company.website)} <ExternalLink size={12} /></a>
                ) : (
                  <span className="drawer-domain muted">No website found yet</span>
                )}
              </div>
            </div>

            <div className="detail-tags">
              {company.industry && <span>{company.industry}</span>}
              {(company.sectors || []).filter((sector) => sector !== company.industry).map((sector) => <span key={sector} className="sector">{sector}</span>)}
              {company.stage && <span>{company.stage}</span>}
              {company.status && <span>{company.status}</span>}
              {company.is_remote && <span>Remote-friendly</span>}
              {(company.is_hiring || (company.open_jobs_count || 0) > 0) && <span className="hiring">Hiring</span>}
              {company.accelerator_batch && <span>YC {company.accelerator_batch}</span>}
            </div>

            <label className={`viewed-toggle ${company.viewed ? "on" : ""}`}>
              <input type="checkbox" checked={company.viewed} onChange={(event) => void toggleViewed(event.target.checked)} />
              <span className="viewed-box">{company.viewed && <Check size={13} />}</span>
              <span>{company.viewed ? `Viewed ${relativeTime(company.viewed_at)}` : "Not viewed"}</span>
              <small>Uncheck to mark as unviewed</small>
            </label>

            <section className="drawer-section">
              <div className="section-title">
                <h3>My note</h3>
                <span className={`note-status ${noteState}`}>
                  {noteState === "saving" ? "Saving…" : noteState === "saved" ? "Saved" : noteState === "error" ? "Not saved" : company.note_updated_at ? `Updated ${relativeTime(company.note_updated_at)}` : "Private to you"}
                </span>
              </div>
              <textarea
                className="note-input"
                rows={4}
                value={note}
                maxLength={20000}
                onChange={(event) => changeNote(event.target.value)}
                placeholder="Contacts, application status, why it is interesting…"
              />
            </section>

            {company.description && <p className="detail-description">{company.description}</p>}

            <dl className="detail-grid">
              <div><dt>Location</dt><dd>{company.location || [company.city, company.state, company.country].filter(Boolean).join(", ") || "—"}</dd></div>
              <div>
                <dt>Founded</dt>
                <dd>
                  {company.founded_year ? `${estimated ? "~" : ""}${company.founded_on && !estimated ? shortDate(company.founded_on) : company.founded_year}` : "Unknown"}
                  {company.founded_source && <small>{label(FOUNDED_SOURCE_LABELS, company.founded_source)}</small>}
                </dd>
              </div>
              <div>
                <dt>Website</dt>
                <dd>
                  {label(WEBSITE_STATUS_LABELS, company.website_status) === "—" ? (company.website ? "Not checked yet" : "—") : label(WEBSITE_STATUS_LABELS, company.website_status)}
                  {company.website_discovery_source && <small>found via {label(DISCOVERY_LABELS, company.website_discovery_source)}</small>}
                </dd>
              </div>
              <div>
                <dt>Careers page</dt>
                <dd>
                  {company.has_careers_page ? (
                    careers ? <a href={careers} target="_blank" rel="noreferrer">Open careers <ExternalLink size={11} /></a> : "Yes"
                  ) : company.careers_checked_at ? "None found" : "Not checked"}
                  {company.has_careers_page && (
                    <small>
                      {label(PROVIDER_LABELS, company.careers_provider)}
                      {company.open_jobs_count !== null && ` · ${company.open_jobs_count} open job${company.open_jobs_count === 1 ? "" : "s"}`}
                    </small>
                  )}
                </dd>
              </div>
              <div><dt>Team size</dt><dd>{typeof company.metadata?.employees_range === "string" ? company.metadata.employees_range : company.employee_count ?? "—"}</dd></div>
              <div><dt>Total raised</dt><dd>{money(company.total_funding_usd)}<small>{company.round_count} recorded round{company.round_count === 1 ? "" : "s"}</small></dd></div>
              <div><dt>Latest valuation</dt><dd>{money(company.latest_valuation_usd)}{company.latest_valuation_usd ? <small>as reported in the funding news</small> : null}</dd></div>
              <div>
                <dt>Contact email</dt>
                <dd>{email ? <a href={email}>{company.contact_email}</a> : "—"}{email && <small>published on the company&apos;s site</small>}</dd>
              </div>
              <div className="span-2">
                <dt>Profiles</dt>
                <dd>
                  {profiles.length ? (
                    <span className="link-list">
                      {profiles.map(([name, href, handle]) => (
                        <a key={name} href={href} target="_blank" rel="noreferrer">{name} <small>{handle}</small> <ExternalLink size={11} /></a>
                      ))}
                    </span>
                  ) : "—"}
                </dd>
              </div>
              {(company.investors || []).length > 0 && (
                <div className="span-2"><dt>Investors</dt><dd>{(company.investors || []).join(", ")}</dd></div>
              )}
              <div><dt>Domain registered</dt><dd>{shortDate(company.domain_registered_on)}</dd></div>
              <div><dt>Last enriched</dt><dd>{relativeTime(company.enriched_at)}{company.enrichment_error && <small className="error-text">{company.enrichment_error}</small>}</dd></div>
              <div className="span-2">
                <dt>Source</dt>
                <dd>{source ? <a href={source} target="_blank" rel="noreferrer">{company.source_name} <ExternalLink size={11} /></a> : company.source_name} <small>first seen {shortDate(company.first_seen_at)}</small></dd>
              </div>
            </dl>

            <section className="drawer-section">
              <div className="section-title">
                <h3>Funding rounds</h3>
                {isAdmin && <button className="button secondary small" onClick={() => setRoundEditor("new")}><Plus size={14} /> Add round</button>}
              </div>
              {company.funding_rounds.length === 0 && <p className="muted small-text">No funding rounds recorded.</p>}
              <ul className="round-list">
                {company.funding_rounds.map((round) => {
                  const roundSource = safeHref(round.source_url);
                  return (
                    <li key={round.id}>
                      <div>
                        <strong>{round.round_type || "Funding round"}</strong>
                        <span>{shortDate(round.announced_on)} · {round.source_name}{round.investors?.length ? ` · ${round.investors.slice(0, 3).join(", ")}` : ""}{round.valuation_usd ?? round.valuation ? ` · valued ${money(round.valuation_usd ?? round.valuation)}` : ""}</span>
                      </div>
                      <div className="round-amount">
                        <strong>{money(round.amount_usd ?? round.amount)}</strong>
                        <span className="round-actions">
                          {roundSource && <a href={roundSource} target="_blank" rel="noreferrer" aria-label="Open source"><ExternalLink size={13} /></a>}
                          {isAdmin && <button onClick={() => setRoundEditor(round)} aria-label="Edit round"><Pencil size={13} /></button>}
                          {isAdmin && <button onClick={() => void deleteRound(round)} aria-label="Delete round"><Trash2 size={13} /></button>}
                        </span>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>

            {isAdmin && (
              <section className="drawer-section admin-zone">
                <div className="section-title"><h3>Admin</h3></div>
                <div className="admin-actions">
                  <button className="button secondary" onClick={() => setEditing(true)}><Pencil size={15} /> Edit</button>
                  <button className="button secondary" onClick={() => void reEnrich()} disabled={busy === "enrich"}>
                    {busy === "enrich" ? <Loader2 size={15} className="spin" /> : <WandSparkles size={15} />} {busy === "enrich" ? "Enriching…" : "Re-enrich now"}
                  </button>
                  {edited.length > 0 && (
                    <button className="button secondary" onClick={() => void unlock()} disabled={busy === "unlock"} title={`Locked: ${edited.join(", ")}`}>
                      <LockOpen size={15} /> Unlock {edited.length} edited field{edited.length === 1 ? "" : "s"}
                    </button>
                  )}
                  <button className="button danger-outline" onClick={() => setConfirmDelete(true)}><Trash2 size={15} /> Delete</button>
                </div>
                {busy === "enrich" && <p className="muted small-text">Checking the website, careers page, and founding date. This can take up to a minute.</p>}
                {enrichLog && <ul className="enrich-log">{enrichLog.map((line, index) => <li key={index}>{line}</li>)}</ul>}
              </section>
            )}

            <div className="drawer-actions">
              {website && <a href={website} target="_blank" rel="noreferrer"><Globe size={16} /> Visit website</a>}
              {careers && <a href={careers} target="_blank" rel="noreferrer" className="secondary"><Briefcase size={16} /> Careers</a>}
              {email && <a href={email} className="secondary"><Mail size={16} /> Email</a>}
            </div>
          </>
        )}
      </aside>

      {editing && company && (
        <CompanyForm
          company={company}
          onClose={() => setEditing(false)}
          onSaved={(saved) => {
            applyDetail(saved);
            setEditing(false);
            notify("Company updated", "success");
            onDataChanged();
          }}
        />
      )}
      {confirmDelete && company && (
        <ConfirmDialog
          title="Delete company?"
          message={<>Delete <strong>{company.name}</strong>, its funding rounds, and everyone&apos;s notes for it? Future scrapes will skip it.</>}
          confirmLabel="Delete company"
          danger
          busy={busy === "delete"}
          onConfirm={() => void remove()}
          onClose={() => setConfirmDelete(false)}
        />
      )}
      {roundEditor && company && (
        <RoundEditor
          companyId={company.id}
          round={roundEditor === "new" ? null : roundEditor}
          onClose={() => setRoundEditor(null)}
          onSaved={async () => {
            setRoundEditor(null);
            applyDetail(await api<CompanyDetail>(`companies/${companyId}`));
            onDataChanged();
          }}
        />
      )}
    </div>
  );
}

function RoundEditor({
  companyId,
  round,
  onClose,
  onSaved,
}: {
  companyId: string;
  round: FundingRound | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    round_type: round?.round_type || "",
    announced_on: round?.announced_on || "",
    amount_usd: round?.amount_usd?.toString() || "",
    valuation_usd: (round?.valuation_usd ?? round?.valuation)?.toString() || "",
    investors: round?.investors?.join(", ") || "",
    source_url: round?.source_url || "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    const payload = {
      round_type: form.round_type || null,
      announced_on: form.announced_on || null,
      amount_usd: form.amount_usd ? Number(form.amount_usd) : null,
      amount: form.amount_usd ? Number(form.amount_usd) : null,
      currency: "USD",
      valuation_usd: form.valuation_usd ? Number(form.valuation_usd) : null,
      valuation: form.valuation_usd ? Number(form.valuation_usd) : null,
      valuation_currency: form.valuation_usd ? "USD" : null,
      investors: form.investors.split(",").map((item) => item.trim()).filter(Boolean),
      source_url: form.source_url || null,
    };
    try {
      if (round) await api(`admin/funding-rounds/${round.id}`, { method: "PATCH", json: payload });
      else await api("admin/funding-rounds", { method: "POST", json: { ...payload, company_id: companyId } });
      onSaved();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save round");
      setSaving(false);
    }
  }

  return (
    <Modal title={round ? "Edit funding round" : "Add funding round"} onClose={onClose}>
      <form onSubmit={submit}>
        <div className="modal-body form-grid">
          <label className="field"><span className="field-label">Round type</span><input className="text-input" value={form.round_type} onChange={(event) => setForm({ ...form, round_type: event.target.value })} placeholder="Seed, Series A…" /></label>
          <label className="field"><span className="field-label">Announced on</span><input className="text-input" type="date" value={form.announced_on} onChange={(event) => setForm({ ...form, announced_on: event.target.value })} /></label>
          <label className="field"><span className="field-label">Amount (USD)</span><input className="text-input" type="number" min={0} value={form.amount_usd} onChange={(event) => setForm({ ...form, amount_usd: event.target.value })} /></label>
          <label className="field"><span className="field-label">Valuation (USD)</span><input className="text-input" type="number" min={0} value={form.valuation_usd} onChange={(event) => setForm({ ...form, valuation_usd: event.target.value })} /></label>
          <label className="field"><span className="field-label">Investors (comma separated)</span><input className="text-input" value={form.investors} onChange={(event) => setForm({ ...form, investors: event.target.value })} /></label>
          <label className="field span-2"><span className="field-label">Source URL</span><input className="text-input" value={form.source_url} onChange={(event) => setForm({ ...form, source_url: event.target.value })} placeholder="https://…" /></label>
        </div>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="modal-footer">
          <button type="button" className="button secondary" onClick={onClose} disabled={saving}>Cancel</button>
          <button type="submit" className="button primary" disabled={saving}>{saving ? "Saving…" : "Save round"}</button>
        </div>
      </form>
    </Modal>
  );
}
