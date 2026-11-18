from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException, status

from startup_scraper.supabase import auth_headers, in_list

from .config import Settings


SCHEMA_ERRORS = {"PGRST202", "PGRST204", "PGRST205", "42703", "42883", "42P01"}
_client: httpx.AsyncClient | None = None
_client_loop: asyncio.AbstractEventLoop | None = None


def http_client() -> httpx.AsyncClient:
    """Shared connection pool, bound to the running event loop (re-created if the loop changes)."""
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    if _client is None or _client.is_closed or _client_loop is not loop:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), limits=httpx.Limits(max_connections=40))
        _client_loop = loop
    return _client


async def close_http_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


class SupabaseAPI:
    """Async PostgREST client authenticated with the service-role key (server side only)."""

    def __init__(self, settings: Settings):
        self.base = settings.supabase_url.rstrip("/")
        self.headers = auth_headers(settings.supabase_service_role_key)

    async def request(
        self,
        method: str,
        path: str,
        query: str = "",
        body: Any = None,
        *,
        prefer: str | None = None,
    ) -> httpx.Response:
        headers = dict(self.headers)
        if prefer:
            headers["Prefer"] = prefer
        url = f"{self.base}/rest/v1/{path}{'?' + query if query else ''}"
        try:
            response = await http_client().request(method, url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            reason = str(exc) or exc.__class__.__name__
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, f"Could not reach Supabase at {httpx.URL(self.base).host} ({reason})"
            ) from exc
        if response.status_code >= 400:
            raise self._error(response)
        return response

    @staticmethod
    def _error(response: httpx.Response) -> HTTPException:
        try:
            payload = response.json()
        except ValueError:
            payload = {"message": response.text[:300]}
        code = str(payload.get("code") or "")
        message = payload.get("message") or payload.get("msg") or "Database error"
        if code in SCHEMA_ERRORS:
            return HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "The database schema is out of date. Run supabase/migrations/003_roles_notes_views_enrichment.sql "
                f"in the Supabase SQL editor. ({code}: {message})",
            )
        if response.status_code in {401, 403}:
            return HTTPException(status.HTTP_502_BAD_GATEWAY, "Supabase rejected the backend key. Use a service-role/secret key.")
        if code == "23505":
            return HTTPException(status.HTTP_409_CONFLICT, f"Duplicate value: {payload.get('details') or message}")
        if code == "23503":
            return HTTPException(status.HTTP_404_NOT_FOUND, "The related company no longer exists")
        if code in {"22P02", "23502", "23514", "22007", "22008"}:
            return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)
        return HTTPException(status.HTTP_502_BAD_GATEWAY, f"Database error ({response.status_code}): {message}")

    async def select(self, table: str, query: str, *, count: bool = False) -> tuple[list[dict[str, Any]], int | None]:
        response = await self.request("GET", table, query, prefer="count=exact" if count else None)
        total = None
        if count and response.headers.get("content-range"):
            tail = response.headers["content-range"].split("/")[-1]
            total = int(tail) if tail.isdigit() else None
        return response.json(), total

    async def insert(
        self, table: str, body: dict[str, Any] | list[dict[str, Any]], *, upsert: str | None = None
    ) -> list[dict[str, Any]]:
        query = f"on_conflict={quote(upsert)}" if upsert else ""
        prefer = "resolution=merge-duplicates,return=representation" if upsert else "return=representation"
        response = await self.request("POST", table, query, body, prefer=prefer)
        return response.json()

    async def update(self, table: str, query: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        response = await self.request("PATCH", table, query, body, prefer="return=representation")
        return response.json()

    async def delete(self, table: str, query: str) -> list[dict[str, Any]]:
        response = await self.request("DELETE", table, query, prefer="return=representation")
        return response.json()

    async def rpc(self, function: str, args: dict[str, Any]) -> Any:
        response = await self.request("POST", f"rpc/{function}", body=args)
        return response.json()


def eq(value: str) -> str:
    return "eq." + quote(str(value), safe="")


def in_filter(values: list[str]) -> str:
    return "in." + quote(in_list(values), safe='(),"')
