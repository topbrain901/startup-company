"use client";

import { Building2, Database, LogOut, Menu, ShieldCheck, TrendingUp, Users } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import CompaniesView from "../components/dashboard/companies-view";
import { Toast } from "../components/dashboard/controls";
import ScraperView from "../components/dashboard/scraper-view";
import UsersView from "../components/dashboard/users-view";
import ThemeSwitch from "../components/theme-switch";
import { initials } from "../lib/format";
import type { Me } from "../lib/types";

type View = "companies" | "scraper" | "users";
type ToastMessage = { id: number; message: string; tone: "info" | "error" | "success" };

const NAV: Array<{ view: View; label: string; icon: typeof Building2; adminOnly: boolean }> = [
  { view: "companies", label: "Companies", icon: Building2, adminOnly: false },
  { view: "scraper", label: "Scraper", icon: Database, adminOnly: true },
  { view: "users", label: "Users", icon: Users, adminOnly: true },
];

function viewFromHash(isAdmin: boolean): View {
  const hash = window.location.hash.replace("#", "") as View;
  return isAdmin && (hash === "scraper" || hash === "users") ? hash : "companies";
}

export default function DashboardClient({
  user,
  me,
  onSignOut,
}: {
  user: { displayName: string; email: string };
  me: Me;
  onSignOut: () => void;
}) {
  const isAdmin = me.role === "admin";
  // Rendered only in the browser (after the session check), so reading the hash is safe.
  const [view, setView] = useState<View>(() => (typeof window === "undefined" ? "companies" : viewFromHash(isAdmin)));
  const [mobileNav, setMobileNav] = useState(false);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  useEffect(() => {
    const onHash = () => setView(viewFromHash(isAdmin));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [isAdmin]);

  const notify = useCallback((message: string, tone: ToastMessage["tone"] = "info") => {
    setToasts((current) => [...current.slice(-3), { id: Date.now() + Math.random(), message, tone }]);
  }, []);
  const dismiss = useCallback((id: number) => setToasts((current) => current.filter((toast) => toast.id !== id)), []);

  function go(next: View) {
    const url = new URL(window.location.href);
    url.hash = next === "companies" ? "" : next;
    if (next !== "companies") url.search = "";
    window.history.pushState(null, "", url.toString());
    setView(next);
    setMobileNav(false);
  }

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileNav ? "sidebar-open" : ""}`}>
        <div className="brand">
          <div className="brand-mark"><TrendingUp size={19} /></div>
          <div><strong>Funding Radar</strong><span>Startup intelligence</span></div>
        </div>
        <nav className="nav-list" aria-label="Primary navigation">
          {NAV.filter((item) => !item.adminOnly || isAdmin).map(({ view: target, label, icon: Icon }) => (
            <button key={target} className={`nav-item ${view === target ? "active" : ""}`} onClick={() => go(target)} aria-current={view === target ? "page" : undefined}>
              <Icon size={18} /><span>{label}</span>{view === target && <span className="nav-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-insight">
          <div className="insight-icon">{isAdmin ? <ShieldCheck size={17} /> : <Building2 size={17} />}</div>
          <strong>{isAdmin ? "Administrator" : "Member"}</strong>
          <p>{isAdmin ? "You can run scrapes and add, edit, or delete companies." : "Browse companies, keep private notes, and track what you have viewed."}</p>
        </div>
        <ThemeSwitch className="sidebar-theme" />
        <div className="sidebar-user">
          <div className="avatar">{initials(user.displayName)}</div>
          <div className="user-copy"><strong>{user.displayName}</strong><span>{user.email}</span></div>
          <button className="sign-out-button" onClick={onSignOut} aria-label="Sign out"><LogOut size={19} /></button>
        </div>
      </aside>

      {mobileNav && <button className="backdrop" onClick={() => setMobileNav(false)} aria-label="Close navigation" />}

      <main className="main-content">
        <header className="topbar">
          <button className="mobile-menu" onClick={() => setMobileNav(true)} aria-label="Open navigation"><Menu /></button>
          <div>
            <p className="eyebrow">{view === "companies" ? "FUNDED COMPANIES" : "ADMINISTRATION"}</p>
            <h1>{view === "companies" ? "Startup funding intelligence" : view === "scraper" ? "Data collection" : "Team access"}</h1>
          </div>
          <span className={`role-pill ${isAdmin ? "admin" : ""}`}>{isAdmin ? "Admin" : "User"}</span>
        </header>

        {view === "companies" && <CompaniesView isAdmin={isAdmin} notify={notify} />}
        {view === "scraper" && isAdmin && <ScraperView notify={notify} />}
        {view === "users" && isAdmin && <UsersView me={me} notify={notify} />}
      </main>

      <div className="toast-stack">
        {toasts.map((toast) => <Toast key={toast.id} id={toast.id} message={toast.message} tone={toast.tone} onDismiss={dismiss} />)}
      </div>
    </div>
  );
}
