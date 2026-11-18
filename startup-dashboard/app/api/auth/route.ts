import { NextRequest, NextResponse } from "next/server";
import {
  ACCESS_COOKIE,
  REFRESH_COOKIE,
  clearSessionCookies,
  getUser,
  passwordAuth,
  publicUser,
  refreshSession,
  setSessionCookies,
} from "../../../lib/supabase-auth";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  let user = await getUser(request.cookies.get(ACCESS_COOKIE)?.value);
  let refreshed = null;
  if (!user) {
    refreshed = await refreshSession(request.cookies.get(REFRESH_COOKIE)?.value);
    user = refreshed?.access_token ? await getUser(refreshed.access_token) : null;
  }
  if (!user) return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  const response = NextResponse.json({ user: publicUser(user) });
  if (refreshed) setSessionCookies(response, refreshed);
  return response;
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json() as { mode?: string; email?: string; password?: string };
    const mode = body.mode === "signup" ? "signup" : "login";
    const email = (body.email || "").trim().toLowerCase();
    const password = body.password || "";
    if (!email || password.length < 6) return NextResponse.json({ error: "Enter a valid email and a password of at least 6 characters." }, { status: 400 });
    const payload = await passwordAuth(mode, email, password);
    if (!payload.access_token || !payload.user) {
      return NextResponse.json({ message: "Check your email to confirm your account, then sign in." });
    }
    const response = NextResponse.json({ user: publicUser(payload.user) });
    setSessionCookies(response, payload);
    return response;
  } catch (reason) {
    return NextResponse.json({ error: reason instanceof Error ? reason.message : "Authentication failed" }, { status: 401 });
  }
}

export async function DELETE() {
  const response = NextResponse.json({ signedOut: true });
  clearSessionCookies(response);
  return response;
}
