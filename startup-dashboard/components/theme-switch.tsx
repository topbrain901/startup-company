"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";
import {
  getServerThemePreference,
  getThemePreference,
  setThemePreference,
  subscribeTheme,
  type ThemePreference,
} from "../lib/theme";

const OPTIONS: Array<{ value: ThemePreference; label: string; title: string; icon: typeof Sun }> = [
  { value: "system", label: "Auto", title: "Match device setting", icon: Monitor },
  { value: "light", label: "Light", title: "Light theme", icon: Sun },
  { value: "dark", label: "Dark", title: "Dark theme", icon: Moon },
];

/** Auto / Light / Dark switch. `compact` shows icons only. */
export default function ThemeSwitch({ compact = false, className = "" }: { compact?: boolean; className?: string }) {
  const preference = useSyncExternalStore(subscribeTheme, getThemePreference, getServerThemePreference);
  return (
    <div className={`theme-switch ${compact ? "compact" : ""} ${className}`} role="radiogroup" aria-label="Color theme">
      {OPTIONS.map(({ value, label, title, icon: Icon }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={preference === value}
          aria-label={compact ? title : undefined}
          title={title}
          className={preference === value ? "active" : ""}
          onClick={() => setThemePreference(value)}
        >
          <Icon size={14} aria-hidden="true" />
          {!compact && <span>{label}</span>}
        </button>
      ))}
    </div>
  );
}
