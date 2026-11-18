from __future__ import annotations

import base64
import json
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote

from .http import HttpClient


def auth_headers(key: str) -> dict[str, str]:
    headers = {"apikey": key, "Content-Type": "application/json"}
    # Legacy service-role keys are JWTs and belong in both headers. New sb_secret_ keys are
    # opaque and must not be presented as bearer JWTs.
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def in_list(values: Iterable[str]) -> str:
    """PostgREST in.(...) operand with quoted values."""
    return "(" + ",".join('"' + str(value).replace('"', "") + '"' for value in values) + ")"


class SupabaseStore:
    """Synchronous PostgREST client used by the collector, enrichment, and background jobs.

    Writes are tagged with an X-Data-Origin header. Database triggers use it so that a
    re-scrape never erases enriched or administrator-edited values.
    """

    def __init__(self, url: str, key: str, client: HttpClient | None = None, origin: str = "scraper"):
        self.url = url.rstrip("/")
        self.key = key
        self.client = client or HttpClient()
        self.headers = auth_headers(key)
        self.origin = origin

    def _legacy_jwt_role(self) -> str | None:
        if not self.key.startswith("eyJ"):
            return None
        try:
            payload = self.key.split(".", 2)[1]
            payload += "=" * (-len(payload) % 4)
            return json.loads(base64.urlsafe_b64decode(payload))["role"]
        except (IndexError, KeyError, ValueError, json.JSONDecodeError):
            return None

    def check_schema(self) -> None:
        role = self._legacy_jwt_role()
        if role == "anon" or self.key.startswith("sb_publishable_"):
            raise RuntimeError(
                "SUPABASE_KEY is an anon/publishable key. This collector needs a "
                "server-only service_role JWT or sb_secret_ key; anon writes are disabled."
            )
        url = f"{self.url}/rest/v1/startup_companies?select=id,entity_kind,edited_fields&limit=1"
        try:
            self.client.request(url, headers=self.headers)
        except RuntimeError as exc:
            raise RuntimeError(
                "Supabase connection check failed. Confirm SUPABASE_URL, apply every SQL file in "
                "supabase/migrations (in order), and set SUPABASE_KEY to a server-side "
                f"service-role/secret key. Details: {exc}"
            ) from exc

    # -- generic helpers -------------------------------------------------------
    def select(self, table: str, query: str) -> list[dict[str, Any]]:
        data = self.client.request(f"{self.url}/rest/v1/{table}?{query}", headers=self.headers, retries=2)
        return json.loads(data)

    def patch(self, table: str, query: str, body: dict[str, Any], *, origin: str | None = None) -> list[dict[str, Any]]:
        headers = {**self.headers, "Prefer": "return=representation", "X-Data-Origin": origin or self.origin}
        data = self.client.request(
            f"{self.url}/rest/v1/{table}?{query}",
            method="PATCH",
            headers=headers,
            body=json.dumps(body, ensure_ascii=False, allow_nan=False, default=str).encode("utf-8"),
            retries=2,
        )
        return json.loads(data) if data else []

    def insert(self, table: str, body: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
        headers = {**self.headers, "Prefer": "return=representation", "X-Data-Origin": self.origin}
        data = self.client.request(
            f"{self.url}/rest/v1/{table}",
            method="POST",
            headers=headers,
            body=json.dumps(body, ensure_ascii=False, allow_nan=False, default=str).encode("utf-8"),
            retries=2,
        )
        return json.loads(data) if data else []

    @staticmethod
    def _chunks(rows: list[dict[str, Any]], size: int = 250):
        for index in range(0, len(rows), size):
            yield rows[index : index + size]

    def _upsert(self, table: str, rows: list[dict[str, Any]], conflict: str) -> list[dict[str, Any]]:
        if not rows:
            return []
        results: list[dict[str, Any]] = []
        for chunk in self._chunks(rows):
            url = f"{self.url}/rest/v1/{table}?on_conflict={quote(conflict)}"
            headers = {
                **self.headers,
                "Prefer": "resolution=merge-duplicates,return=representation",
                "X-Data-Origin": self.origin,
            }
            data = self.client.request(
                url,
                method="POST",
                headers=headers,
                body=json.dumps(chunk, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            )
            results.extend(json.loads(data))
        return results

    def save(self, companies: Iterable[Any], rounds: Iterable[Any]) -> tuple[int, int]:
        company_rows = [item.row() for item in companies]
        # first_seen_at and curated fields are preserved by database triggers on conflict.
        saved_companies = self._upsert("startup_companies", company_rows, "source_key")
        ids = {row["source_key"]: row["id"] for row in saved_companies}
        round_rows = []
        for item in rounds:
            row = item.row()
            company_key = row.pop("company_source_key")
            company_id = ids.get(company_key)
            if company_id:
                row["company_id"] = company_id
                round_rows.append(row)
        saved_rounds = self._upsert("funding_rounds", round_rows, "source_key")
        return len(saved_companies), len(saved_rounds)

    # -- enrichment helpers ------------------------------------------------------
    ENRICH_COLUMNS = (
        "id,name,website,domain,description,city,state,country,source_name,source_url,entity_kind,"
        "founded_year,founded_source,website_status,website_discovery_source,edited_fields,metadata"
    )

    def enrichment_rows(self, ids: list[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for index in range(0, len(ids), 100):
            operand = quote(in_list(ids[index : index + 100]), safe='(),"')
            rows.extend(self.select("startup_companies", f"select={self.ENRICH_COLUMNS}&id=in.{operand}"))
        order = {company_id: position for position, company_id in enumerate(ids)}
        return sorted(rows, key=lambda row: order.get(row["id"], 0))

    def save_enrichment(self, company_id: str, patch: dict[str, Any]) -> None:
        self.patch("startup_companies", f"id=eq.{quote(company_id)}", patch, origin="enricher")
