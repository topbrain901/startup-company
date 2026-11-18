"use client";

import { Check, ChevronDown, Search, X } from "lucide-react";
import { ReactNode, useEffect, useId, useMemo, useRef, useState } from "react";
import type { FacetValue } from "../../lib/types";

export function MultiSelect({
  label,
  options,
  value,
  onChange,
  placeholder = "Any",
  formatOption = (text) => text,
}: {
  label: string;
  options: FacetValue[];
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  formatOption?: (value: string) => string;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    const merged = [...options];
    for (const selected of value) {
      if (!merged.some((option) => option.value === selected)) merged.unshift({ value: selected, count: 0 });
    }
    return term ? merged.filter((option) => formatOption(option.value).toLowerCase().includes(term)) : merged;
  }, [options, value, search, formatOption]);

  const toggle = (item: string) =>
    onChange(value.includes(item) ? value.filter((entry) => entry !== item) : [...value, item]);

  const summary = value.length === 0 ? placeholder : value.length === 1 ? formatOption(value[0]) : `${value.length} selected`;

  return (
    <div className="field" ref={root}>
      <span className="field-label" id={`${id}-label`}>{label}</span>
      <button
        type="button"
        className={`select-trigger ${value.length ? "has-value" : ""}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-labelledby={`${id}-label`}
        onClick={() => setOpen((current) => !current)}
      >
        <span>{summary}</span>
        {value.length > 0 ? (
          <span
            className="select-clear"
            role="button"
            tabIndex={0}
            aria-label={`Clear ${label}`}
            onClick={(event) => { event.stopPropagation(); onChange([]); }}
            onKeyDown={(event) => { if (event.key === "Enter") { event.stopPropagation(); onChange([]); } }}
          >
            <X size={13} />
          </span>
        ) : (
          <ChevronDown size={15} />
        )}
      </button>
      {open && (
        <div className="select-popover" role="listbox" aria-multiselectable="true">
          {options.length > 8 && (
            <label className="select-search">
              <Search size={14} />
              <input autoFocus value={search} onChange={(event) => setSearch(event.target.value)} placeholder={`Search ${label.toLowerCase()}…`} />
            </label>
          )}
          <div className="select-options">
            {visible.length === 0 && <p className="select-empty">No matches</p>}
            {visible.slice(0, 300).map((option) => {
              const checked = value.includes(option.value);
              return (
                <button
                  type="button"
                  role="option"
                  aria-selected={checked}
                  key={option.value}
                  className={checked ? "selected" : ""}
                  onClick={() => toggle(option.value)}
                >
                  <span className="checkbox-box">{checked && <Check size={12} />}</span>
                  <span className="option-text">{formatOption(option.value)}</span>
                  {option.count > 0 && <span className="option-count">{option.count.toLocaleString()}</span>}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: Array<{ value: T; label: string }>;
  onChange: (next: T) => void;
}) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <div className="segmented" role="radiogroup" aria-label={label}>
        {options.map((option) => (
          <button
            type="button"
            role="radio"
            aria-checked={value === option.value}
            key={option.value || "any"}
            className={value === option.value ? "active" : ""}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (next: string) => void;
}) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <select className="native-select" value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </label>
  );
}

export function NumberRange({
  label,
  from,
  to,
  onChange,
  placeholderFrom = "From",
  placeholderTo = "To",
  min,
  max,
}: {
  label: string;
  from: string;
  to: string;
  onChange: (from: string, to: string) => void;
  placeholderFrom?: string;
  placeholderTo?: string;
  min?: number;
  max?: number;
}) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <div className="range-inputs">
        <input type="number" inputMode="numeric" min={min} max={max} value={from} placeholder={placeholderFrom} aria-label={`${label} from`} onChange={(event) => onChange(event.target.value, to)} />
        <span>–</span>
        <input type="number" inputMode="numeric" min={min} max={max} value={to} placeholder={placeholderTo} aria-label={`${label} to`} onChange={(event) => onChange(from, event.target.value)} />
      </div>
    </div>
  );
}

export function Modal({ title, onClose, children, wide = false }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const escape = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [onClose]);
  return (
    <div className="modal-layer" role="dialog" aria-modal="true" aria-label={title}>
      <button className="modal-backdrop" onClick={onClose} aria-label="Close dialog" />
      <div className={`modal ${wide ? "modal-wide" : ""}`}>
        <div className="modal-header">
          <h3>{title}</h3>
          <button className="icon-button" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  danger = false,
  busy = false,
  onConfirm,
  onClose,
}: {
  title: string;
  message: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Modal title={title} onClose={onClose}>
      <div className="modal-body"><p className="confirm-text">{message}</p></div>
      <div className="modal-footer">
        <button className="button secondary" onClick={onClose} disabled={busy}>Cancel</button>
        <button className={`button ${danger ? "danger" : "primary"}`} onClick={onConfirm} disabled={busy}>{busy ? "Working…" : confirmLabel}</button>
      </div>
    </Modal>
  );
}

export function Toast({
  id,
  message,
  tone = "info",
  onDismiss,
}: {
  id: number;
  message: string;
  tone?: "info" | "error" | "success";
  onDismiss: (id: number) => void;
}) {
  useEffect(() => {
    const timer = window.setTimeout(() => onDismiss(id), tone === "error" ? 7000 : 3500);
    return () => window.clearTimeout(timer);
  }, [id, onDismiss, tone]);
  return (
    <div className={`toast toast-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <span>{message}</span>
      <button onClick={() => onDismiss(id)} aria-label="Dismiss"><X size={14} /></button>
    </div>
  );
}
