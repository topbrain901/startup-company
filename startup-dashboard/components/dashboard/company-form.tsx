"use client";

import { FormEvent, useState } from "react";
import { api } from "../../lib/api";
import { KIND_LABELS } from "../../lib/format";
import type { CompanyDetail } from "../../lib/types";
import { Modal } from "./controls";

type FormState = Record<string, string>;

const TEXT_FIELDS: Array<{ key: string; label: string; placeholder?: string; wide?: boolean }> = [
  { key: "name", label: "Company name *" },
  { key: "website", label: "Website", placeholder: "acme.com" },
  { key: "city", label: "City" },
  { key: "state", label: "State / region" },
  { key: "country", label: "Country", placeholder: "United States" },
  { key: "industry", label: "Industry" },
  { key: "subindustry", label: "Sub-industry" },
  { key: "stage", label: "Stage", placeholder: "Early, Growth…" },
  { key: "status", label: "Status", placeholder: "Active, Acquired…" },
  { key: "accelerator_batch", label: "Accelerator batch" },
  { key: "founded_year", label: "Founded year", placeholder: "2021" },
  { key: "employee_count", label: "Team size" },
  { key: "careers_url", label: "Careers page URL", wide: true },
  { key: "open_jobs_count", label: "Open jobs" },
];
const NUMBER_FIELDS = new Set(["founded_year", "employee_count", "open_jobs_count"]);
const TRI_STATE_FIELDS = ["is_remote", "is_hiring", "has_careers_page"] as const;

function initialState(company?: CompanyDetail | null): FormState {
  const state: FormState = { description: company?.description || "", entity_kind: company?.entity_kind || "startup" };
  for (const field of TEXT_FIELDS) {
    const value = company ? (company as unknown as Record<string, unknown>)[field.key] : null;
    state[field.key] = value === null || value === undefined ? "" : String(value);
  }
  for (const key of TRI_STATE_FIELDS) {
    const value = company ? company[key] : null;
    state[key] = value === true ? "yes" : value === false ? "no" : "";
  }
  return state;
}

function payloadFrom(state: FormState, original: FormState, isNew: boolean): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(state)) {
    if (!isNew && value === original[key]) continue;
    if ((TRI_STATE_FIELDS as readonly string[]).includes(key)) payload[key] = value === "" ? null : value === "yes";
    else if (NUMBER_FIELDS.has(key)) payload[key] = value.trim() === "" ? null : Number(value);
    else payload[key] = value.trim() === "" ? null : value.trim();
  }
  if (isNew) for (const key of Object.keys(payload)) if (payload[key] === null) delete payload[key];
  return payload;
}

export default function CompanyForm({
  company,
  onClose,
  onSaved,
}: {
  company?: CompanyDetail | null;
  onClose: () => void;
  onSaved: (company: CompanyDetail) => void;
}) {
  const [original] = useState(() => initialState(company));
  const [state, setState] = useState(original);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const isNew = !company;
  const set = (key: string, value: string) => setState((current) => ({ ...current, [key]: value }));

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const payload = payloadFrom(state, original, isNew);
      const saved = isNew
        ? await api<CompanyDetail>("admin/companies", { method: "POST", json: payload })
        : Object.keys(payload).length
          ? await api<CompanyDetail>(`admin/companies/${company!.id}`, { method: "PATCH", json: payload })
          : company!;
      onSaved(saved);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save the company");
      setSaving(false);
    }
  }

  return (
    <Modal title={isNew ? "Add company" : `Edit ${company!.name}`} onClose={onClose} wide>
      <form onSubmit={submit}>
        <div className="modal-body form-grid">
          {TEXT_FIELDS.map((field) => (
            <label className={`field ${field.wide ? "span-2" : ""}`} key={field.key}>
              <span className="field-label">{field.label}</span>
              <input
                className="text-input"
                value={state[field.key]}
                required={field.key === "name"}
                type={NUMBER_FIELDS.has(field.key) ? "number" : "text"}
                min={NUMBER_FIELDS.has(field.key) ? 0 : undefined}
                placeholder={field.placeholder}
                onChange={(event) => set(field.key, event.target.value)}
              />
            </label>
          ))}
          <label className="field">
            <span className="field-label">Company type</span>
            <select className="native-select" value={state.entity_kind} onChange={(event) => set("entity_kind", event.target.value)}>
              {Object.entries(KIND_LABELS).map(([value, text]) => <option key={value} value={value}>{text}</option>)}
            </select>
          </label>
          {([
            ["has_careers_page", "Careers page"],
            ["is_hiring", "Hiring"],
            ["is_remote", "Remote-friendly"],
          ] as const).map(([key, text]) => (
            <label className="field" key={key}>
              <span className="field-label">{text}</span>
              <select className="native-select" value={state[key]} onChange={(event) => set(key, event.target.value)}>
                <option value="">Unknown</option>
                <option value="yes">Yes</option>
                <option value="no">No</option>
              </select>
            </label>
          ))}
          <label className="field span-2">
            <span className="field-label">Description</span>
            <textarea className="text-area" rows={4} value={state.description} onChange={(event) => set("description", event.target.value)} />
          </label>
          {!isNew && (
            <p className="form-hint span-2">
              Fields you change here are locked: future scrapes and enrichment will not overwrite them.
            </p>
          )}
        </div>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="modal-footer">
          <button type="button" className="button secondary" onClick={onClose} disabled={saving}>Cancel</button>
          <button type="submit" className="button primary" disabled={saving}>{saving ? "Saving…" : isNew ? "Add company" : "Save changes"}</button>
        </div>
      </form>
    </Modal>
  );
}
