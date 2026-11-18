"use client";

import { Eye, EyeOff, LockKeyhole, Mail, ServerCrash, TrendingUp } from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import ThemeSwitch from "../components/theme-switch";
import { ApiError, api } from "../lib/api";
import type { Me } from "../lib/types";
import DashboardClient from "./dashboard-client";

type User = { id: string; email: string; displayName: string };
type AuthPayload = { user?: User; error?: string; message?: string };

export default function AuthShell() {
  const [user, setUser] = useState<User | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [backendError, setBackendError] = useState("");
  const [checking, setChecking] = useState(true);
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // The FastAPI backend decides the role (admin / user).
  const loadRole = useCallback(async () => {
    try {
      const profile = await api<Me>("me");
      setMe(profile);
      setBackendError("");
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) {
        setUser(null);
        setMe(null);
        return;
      }
      setBackendError(reason instanceof Error ? reason.message : "The API is unavailable");
    }
  }, []);

  const checkSession = useCallback(async () => {
    try {
      const response = await fetch("/api/auth", { cache: "no-store" });
      if (!response.ok) return setUser(null);
      const payload = (await response.json()) as AuthPayload;
      setUser(payload.user || null);
      if (payload.user) await loadRole();
    } finally {
      setChecking(false);
    }
  }, [loadRole]);

  useEffect(() => void checkSession(), [checkSession]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch("/api/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, email: email.trim(), password }),
      });
      const payload = (await response.json()) as AuthPayload;
      if (!response.ok) throw new Error(payload.error || "Authentication failed");
      if (payload.user) {
        setUser(payload.user);
        await loadRole();
      } else setNotice(payload.message || "Check your email to confirm your account.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Authentication failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function signOut() {
    await fetch("/api/auth", { method: "DELETE" });
    setUser(null);
    setMe(null);
    setPassword("");
  }

  if (checking || (user && !me && !backendError)) {
    return <div className="auth-loading"><div className="auth-brand-mark"><TrendingUp size={24} /></div><span>Opening Funding Radar…</span></div>;
  }

  if (user && backendError) {
    return (
      <div className="auth-loading backend-down">
        <ServerCrash size={30} />
        <strong>The Funding Radar API is not reachable</strong>
        <p>{backendError}</p>
        <p className="muted small-text">Start it with <code>uvicorn backend.app.main:app --port 8000</code> and set <code>FASTAPI_URL</code> for this site.</p>
        <div className="backend-actions">
          <button className="button primary" onClick={() => { setBackendError(""); void loadRole(); }}>Try again</button>
          <button className="button secondary" onClick={() => void signOut()}>Sign out</button>
        </div>
      </div>
    );
  }

  if (user && me) return <DashboardClient user={user} me={me} onSignOut={() => void signOut()} />;

  return (
    <main className="auth-page">
      <section className="auth-story">
        <div className="auth-brand"><div className="auth-brand-mark"><TrendingUp size={22} /></div><div><strong>Funding Radar</strong><span>Startup intelligence</span></div></div>
        <div className="auth-story-copy">
          <p className="auth-kicker">PRIVATE MARKET INTELLIGENCE</p>
          <h1>See where startup capital is moving.</h1>
          <p>Track newly funded companies, compare rounds, and explore verified public-source signals from one focused dashboard.</p>
          <div className="auth-proof"><div><strong>10K+</strong><span>companies tracked</span></div><div><strong>4K+</strong><span>funding events</span></div><div><strong>3</strong><span>source families</span></div></div>
        </div>
        <p className="auth-footnote">SEC filings · accelerator directories · funding news</p>
      </section>

      <section className="auth-form-side">
        <ThemeSwitch compact className="auth-theme" />
        <form className="auth-card" onSubmit={submit}>
          <div className="auth-card-heading"><p>{mode === "login" ? "WELCOME BACK" : "CREATE ACCOUNT"}</p><h2>{mode === "login" ? "Sign in to your dashboard" : "Start exploring companies"}</h2><span>{mode === "login" ? "Enter your Supabase account credentials." : "Create a secure account with email and password."}</span></div>
          <div className="auth-tabs"><button type="button" className={mode === "login" ? "active" : ""} onClick={() => { setMode("login"); setError(""); setNotice(""); }}>Sign in</button><button type="button" className={mode === "signup" ? "active" : ""} onClick={() => { setMode("signup"); setError(""); setNotice(""); }}>Create account</button></div>
          <label className="auth-field"><span>Email address</span><div><Mail size={19} /><input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" autoComplete="email" required /></div></label>
          <label className="auth-field"><span>Password</span><div><LockKeyhole size={19} /><input type={showPassword ? "text" : "password"} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="At least 6 characters" autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={6} required /><button type="button" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? "Hide password" : "Show password"}>{showPassword ? <EyeOff size={18} /> : <Eye size={18} />}</button></div></label>
          {error && <p className="auth-message error" role="alert">{error}</p>}
          {notice && <p className="auth-message success">{notice}</p>}
          <button className="auth-submit" disabled={submitting}>{submitting ? "Please wait…" : mode === "login" ? "Sign in securely" : "Create account"}</button>
          <p className="auth-security"><LockKeyhole size={14} /> Session tokens are stored in secure HTTP-only cookies.</p>
        </form>
      </section>
    </main>
  );
}
