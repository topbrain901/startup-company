/**
 * Color theme: "system" follows the device setting, "light"/"dark" are explicit choices.
 * The resolved theme is written to <html data-theme="light|dark">; globals.css switches its
 * color tokens on that attribute.
 */
export type ThemePreference = "system" | "light" | "dark";

export const THEME_STORAGE_KEY = "funding-radar-theme";

/**
 * Inlined in <head> so the saved theme is applied before the first paint (no light flash).
 * It also follows device changes while the preference is "system".
 */
export const THEME_BOOT_SCRIPT = `(function(){var k=${JSON.stringify(THEME_STORAGE_KEY)},r=document.documentElement,m=window.matchMedia("(prefers-color-scheme: dark)");function p(){try{var v=localStorage.getItem(k);return v==="light"||v==="dark"?v:"system"}catch(e){return"system"}}function a(){var v=p(),d=v==="dark"||(v==="system"&&m.matches);r.setAttribute("data-theme",d?"dark":"light");r.style.colorScheme=d?"dark":"light"}a();m.addEventListener("change",a)})();`;

const listeners = new Set<() => void>();
let memory: ThemePreference | null = null; // only used when localStorage is blocked

function readStored(): ThemePreference {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return memory || "system";
  }
}

export function applyTheme(preference: ThemePreference): void {
  const dark =
    preference === "dark" || (preference === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  const root = document.documentElement;
  root.dataset.theme = dark ? "dark" : "light";
  root.style.colorScheme = dark ? "dark" : "light";
}

export function getThemePreference(): ThemePreference {
  return readStored();
}

export function getServerThemePreference(): ThemePreference {
  return "system";
}

export function setThemePreference(preference: ThemePreference): void {
  try {
    if (preference === "system") window.localStorage.removeItem(THEME_STORAGE_KEY);
    else window.localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // Storage blocked (site data disabled): the choice lasts until the page is reloaded.
    memory = preference;
  }
  applyTheme(preference);
  listeners.forEach((listener) => listener());
}

/** For useSyncExternalStore: notifies on changes from this tab and from other open tabs. */
export function subscribeTheme(listener: () => void): () => void {
  const onStorage = (event: StorageEvent) => {
    if (event.key !== THEME_STORAGE_KEY && event.key !== null) return;
    applyTheme(readStored());
    listener();
  };
  listeners.add(listener);
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}
