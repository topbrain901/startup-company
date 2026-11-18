import { NextRequest, NextResponse } from "next/server";

export const ACCESS_COOKIE = "funding-radar-access";
export const REFRESH_COOKIE = "funding-radar-refresh";

type AuthPayload = {
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
  user?: { id: string; email?: string; user_metadata?: Record<string, unknown> };
  msg?: string;
  error_description?: string;
};

function authConfig() {
  const url = process.env.SUPABASE_URL?.replace(/\/$/, "");
  const anonKey = process.env.SUPABASE_ANON_KEY;
  if (!url || !anonKey) throw new Error("Supabase authentication is not configured.");
  return { url, anonKey };
}

async function authRequest(path: string, init: RequestInit) {
  const { url, anonKey } = authConfig();
  return fetch(`${url}/auth/v1/${path}`, {
    ...init,
    headers: { apikey: anonKey, "Content-Type": "application/json", ...(init.headers || {}) },
    cache: "no-store",
  });
}

export async function passwordAuth(mode: "login" | "signup", email: string, password: string) {
  const path = mode === "login" ? "token?grant_type=password" : "signup";
  const response = await authRequest(path, { method: "POST", body: JSON.stringify({ email, password }) });
  const payload = (await response.json()) as AuthPayload;
  if (!response.ok) throw new Error(payload.error_description || payload.msg || "Authentication failed");
  return payload;
}

export async function getUser(accessToken: string | undefined) {
  if (!accessToken) return null;
  try {
    const response = await authRequest("user", { headers: { Authorization: `Bearer ${accessToken}` } });
    if (!response.ok) return null;
    return (await response.json()) as { id: string; email?: string; user_metadata?: Record<string, unknown> };
  } catch {
    return null;
  }
}

export async function refreshSession(refreshToken: string | undefined) {
  if (!refreshToken) return null;
  try {
    const response = await authRequest("token?grant_type=refresh_token", { method: "POST", body: JSON.stringify({ refresh_token: refreshToken }) });
    if (!response.ok) return null;
    return (await response.json()) as AuthPayload;
  } catch {
    return null;
  }
}

export function publicUser(user: { id: string; email?: string; user_metadata?: Record<string, unknown> }) {
  const email = user.email || "Authenticated user";
  const fullName = typeof user.user_metadata?.full_name === "string" ? user.user_metadata.full_name : null;
  return { id: user.id, email, displayName: fullName || email.split("@")[0] || email };
}

export function setSessionCookies(response: NextResponse, payload: AuthPayload) {
  if (!payload.access_token || !payload.refresh_token) return;
  const secure = process.env.NODE_ENV === "production";
  response.cookies.set(ACCESS_COOKIE, payload.access_token, { httpOnly: true, secure, sameSite: "lax", path: "/", maxAge: payload.expires_in || 3600 });
  response.cookies.set(REFRESH_COOKIE, payload.refresh_token, { httpOnly: true, secure, sameSite: "lax", path: "/", maxAge: 60 * 60 * 24 * 30 });
}

export function clearSessionCookies(response: NextResponse) {
  response.cookies.set(ACCESS_COOKIE, "", { httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "lax", path: "/", maxAge: 0 });
  response.cookies.set(REFRESH_COOKIE, "", { httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "lax", path: "/", maxAge: 0 });
}

export async function requestUser(request: NextRequest) {
  return getUser(request.cookies.get(ACCESS_COOKIE)?.value);
}
