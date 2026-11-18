import { NextRequest, NextResponse } from "next/server";
import {
  ACCESS_COOKIE,
  REFRESH_COOKIE,
  refreshSession,
  setSessionCookies,
} from "../../../../lib/supabase-auth";

export const dynamic = "force-dynamic";

function backendUrl(path: string[], search: string) {
  const configured = process.env.FASTAPI_URL?.replace(/\/$/, "");
  const base = configured || (process.env.NODE_ENV !== "production" ? "http://127.0.0.1:8000" : "");
  if (!base) throw new Error("The FastAPI backend URL is not configured. Set FASTAPI_URL for this site.");
  return `${base}/${path.map(encodeURIComponent).join("/")}${search}`;
}

const PASSTHROUGH_HEADERS = ["content-type", "content-disposition"];

async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  try {
    const { path } = await context.params;
    let token = request.cookies.get(ACCESS_COOKIE)?.value;
    let refreshed: Awaited<ReturnType<typeof refreshSession>> = null;
    if (!token) {
      refreshed = await refreshSession(request.cookies.get(REFRESH_COOKIE)?.value);
      token = refreshed?.access_token;
    }
    if (!token) return NextResponse.json({ detail: "Authentication required" }, { status: 401 });

    const body = request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await request.arrayBuffer();
    const call = (accessToken: string) => fetch(backendUrl(path, request.nextUrl.search), {
      method: request.method,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        ...(request.headers.get("content-type") ? { "Content-Type": request.headers.get("content-type")! } : {}),
      },
      body,
      cache: "no-store",
    });

    let upstream = await call(token);
    if (upstream.status === 401 && !refreshed) {
      refreshed = await refreshSession(request.cookies.get(REFRESH_COOKIE)?.value);
      if (refreshed?.access_token) upstream = await call(refreshed.access_token);
    }
    const headers = new Headers({ "Cache-Control": "no-store" });
    for (const name of PASSTHROUGH_HEADERS) {
      const value = upstream.headers.get(name);
      if (value) headers.set(name, value);
    }
    const empty = upstream.status === 204 || upstream.status === 304;
    const response = new NextResponse(empty ? null : upstream.body, { status: upstream.status, headers });
    if (refreshed) setSessionCookies(response, refreshed);
    return response;
  } catch (reason) {
    return NextResponse.json(
      { detail: reason instanceof Error ? reason.message : "Backend request failed" },
      { status: 503 },
    );
  }
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
