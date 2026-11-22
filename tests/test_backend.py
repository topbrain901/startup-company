"""API behaviour tests with an in-memory stand-in for Supabase (no network)."""

import os
import unittest
from datetime import date, timedelta

os.environ.setdefault("SUPABASE_URL", "http://supabase.test")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")

try:
    from fastapi.testclient import TestClient
except ImportError:  # backend dependencies not installed
    TestClient = None

if TestClient is not None:
    import backend.app.admin as admin_module
    import backend.app.auth as auth_module
    import backend.app.companies as companies_module
    import backend.app.jobs as jobs_module
    from backend.app.config import get_settings
    from backend.app.main import app


USER_ID = "11111111-1111-4111-8111-111111111111"
ADMIN_ID = "22222222-2222-4222-8222-222222222222"
COMPANY_ID = "33333333-3333-4333-8333-333333333333"
USERS = {
    "user-token": {"id": USER_ID, "email": "user@example.com"},
    "admin-token": {"id": ADMIN_ID, "email": "admin@example.com"},
}
ROLES = {USER_ID: "user", ADMIN_ID: "admin"}


class FakeDB:
    def __init__(self):
        self.calls = []

    def of(self, method, table=None):
        return [call for call in self.calls if call[0] == method and (table is None or call[1] == table)]


class FakeAPI:
    def __init__(self, db):
        self.db = db

    async def select(self, table, query, *, count=False):
        self.db.calls.append(("GET", table, query, None))
        if table == "profiles":
            user_id = USER_ID if USER_ID in query else ADMIN_ID
            return [{"id": user_id, "email": "x", "role": ROLES[user_id]}], None
        if table == "startup_companies" and query.startswith("select=id,edited_fields"):
            return [{"id": COMPANY_ID, "edited_fields": ["name", "normalized_name"]}], None
        if table == "startup_companies" and query.startswith("select=source_key"):
            return [{"source_key": "sec-cik:abc", "name": "Acme", "source_name": "SEC EDGAR Form D"}], None
        if table == "startup_companies" and query.startswith("select=*"):
            return [{"id": COMPANY_ID, "name": "Acme", "funding_rounds": []}], None
        return [], None

    async def insert(self, table, body, *, upsert=None):
        self.db.calls.append(("POST", table, upsert, body))
        rows = body if isinstance(body, list) else [body]
        return [{"id": COMPANY_ID, "updated_at": "2026-11-18T00:00:00Z", **row} for row in rows]

    async def update(self, table, query, body):
        self.db.calls.append(("PATCH", table, query, body))
        return [{"id": COMPANY_ID, **body}]

    async def delete(self, table, query):
        self.db.calls.append(("DELETE", table, query, None))
        return [{"id": COMPANY_ID}]

    async def rpc(self, function, args):
        self.db.calls.append(("RPC", function, None, args))
        if function == "search_companies":
            return {"total": 31, "rows": [{
                "name": "Acme", "website": "https://acme.com", "viewed": True, "note": "Ping CTO",
                "investors": ["Accel", "Sequoia"], "sectors": ["Fintech"], "contact_email": "hello@acme.com",
            }]}
        return {}


@unittest.skipIf(TestClient is None, "backend requirements not installed")
class BackendTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.patches = []
        factory = lambda settings: FakeAPI(self.db)  # noqa: E731
        for module in (auth_module, companies_module, admin_module, jobs_module):
            self.patches.append((module, "SupabaseAPI", module.SupabaseAPI))
            module.SupabaseAPI = factory

        async def verify(token, settings):
            if token not in USERS:
                from fastapi import HTTPException

                raise HTTPException(401, "Invalid or expired session")
            return USERS[token]

        self.patches.append((auth_module, "_verify_token", auth_module._verify_token))
        auth_module._verify_token = verify
        auth_module._cache.clear()
        companies_module.invalidate_facets()
        get_settings().admin_emails = ""
        self.client = TestClient(app)

    def tearDown(self):
        for module, name, original in self.patches:
            setattr(module, name, original)

    def get(self, path, token="user-token", **kwargs):
        return self.client.get(path, headers={"Authorization": f"Bearer {token}"}, **kwargs)

    def send(self, method, path, token="user-token", **kwargs):
        return self.client.request(method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs)

    def test_requires_authentication(self):
        self.assertEqual(self.client.get("/companies").status_code, 401)
        self.assertEqual(self.get("/companies", token="bogus").status_code, 401)

    def test_me_reports_role(self):
        self.assertEqual(self.get("/me").json()["role"], "user")
        self.assertEqual(self.get("/me", token="admin-token").json()["role"], "admin")

    def test_admin_emails_bootstrap(self):
        get_settings().admin_emails = "User@Example.com"
        self.get("/me")
        promotions = [call for call in self.db.of("PATCH", "profiles") if call[3] == {"role": "admin"}]
        self.assertEqual(len(promotions), 1)

    def test_search_translates_filters(self):
        response = self.get(
            "/companies",
            params=[
                ("country", "United States"), ("country", "Canada"), ("careers", "yes"), ("website", "no"),
                ("round_type", "Seed"), ("funded_within", "90"), ("viewed", "no"), ("status", "Active"),
                ("sort", "amount"), ("page", "2"), ("page_size", "10"), ("q", "  robots "),
            ],
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual((body["total"], body["pages"], body["page"]), (31, 4, 2))
        args = self.db.of("RPC")[0][3]
        self.assertEqual(args["p_user_id"], USER_ID)
        p = args["p"]
        self.assertEqual(p["countries"], ["United States", "Canada"])
        self.assertEqual(p["statuses"], ["Active"])
        self.assertEqual((p["careers"], p["website"], p["viewed"], p["sort"], p["q"]), ("yes", "no", "no", "amount", "robots"))
        self.assertEqual(p["round_types"], ["Seed"])
        self.assertEqual(p["funded_after"], (date.today() - timedelta(days=90)).isoformat())
        self.assertEqual((p["limit"], p["offset"]), (10, 10))
        self.assertNotIn("states", p)  # empty filters are omitted

    def test_search_contact_investor_sector_filters(self):
        response = self.get(
            "/companies",
            params=[
                ("sector", "Fintech"), ("sector", "AI & machine learning"), ("investor", " Sequoia "),
                ("email", "yes"), ("linkedin", "no"), ("valuation_min", "100000000"), ("sort", "valuation"),
            ],
        )
        self.assertEqual(response.status_code, 200)
        p = self.db.of("RPC")[0][3]["p"]
        self.assertEqual(p["sectors"], ["Fintech", "AI & machine learning"])
        self.assertEqual((p["investor"], p["email"], p["linkedin"], p["sort"]), ("Sequoia", "yes", "no", "valuation"))
        self.assertEqual(p["valuation_min"], 100_000_000)

    def test_admin_contact_fields_are_normalized_and_locked(self):
        response = self.send(
            "PATCH", f"/admin/companies/{COMPANY_ID}", token="admin-token",
            json={"linkedin_url": "linkedin.com/company/acme", "twitter_url": "@acme", "contact_email": " Hello@Acme.com "},
        )
        self.assertEqual(response.status_code, 200)
        body = self.db.of("PATCH", "startup_companies")[0][3]
        self.assertEqual(body["linkedin_url"], "https://www.linkedin.com/company/acme")
        self.assertEqual((body["twitter_url"], body["contact_email"]), ("https://x.com/acme", "hello@acme.com"))
        for field in ("linkedin_url", "twitter_url", "contact_email"):
            self.assertIn(field, body["edited_fields"])

    def test_admin_rejects_bad_contact_fields(self):
        for payload in ({"linkedin_url": "https://www.linkedin.com/in/jane"}, {"contact_email": "not-an-email"}):
            response = self.send("PATCH", f"/admin/companies/{COMPANY_ID}", token="admin-token", json=payload)
            self.assertEqual(response.status_code, 422, payload)

    def test_round_valuation_in_usd(self):
        response = self.send(
            "POST", "/admin/funding-rounds", token="admin-token",
            json={"company_id": COMPANY_ID, "round_type": "Series A", "amount": 5e6, "valuation_usd": 4e7},
        )
        self.assertEqual(response.status_code, 201)
        body = self.db.of("POST", "funding_rounds")[0][3]
        self.assertEqual((body["valuation"], body["valuation_currency"], body["valuation_usd"]), (4e7, "USD", 4e7))

    def test_rejects_bad_filter_values(self):
        self.assertEqual(self.get("/companies", params={"careers": "maybe"}).status_code, 422)
        self.assertEqual(self.get("/companies", params={"founded_from": "99"}).status_code, 422)

    def test_users_cannot_use_admin_endpoints(self):
        self.assertEqual(self.send("POST", "/admin/companies", json={"name": "X"}).status_code, 403)
        self.assertEqual(self.send("POST", "/admin/jobs/collect", json={}).status_code, 403)
        self.assertEqual(self.get("/admin/users").status_code, 403)

    def test_admin_edit_pins_fields(self):
        response = self.send(
            "PATCH", f"/admin/companies/{COMPANY_ID}", token="admin-token",
            json={"website": "acme.com", "founded_year": 2019, "careers_url": "https://acme.com/jobs"},
        )
        self.assertEqual(response.status_code, 200)
        body = self.db.of("PATCH", "startup_companies")[0][3]
        self.assertEqual((body["website"], body["domain"], body["website_discovery_source"]), ("https://acme.com", "acme.com", "manual"))
        self.assertEqual((body["founded_source"], body["has_careers_page"], body["careers_provider"]), ("manual", True, "manual"))
        for field in ("name", "website", "domain", "founded_year", "founded_source", "careers_url", "has_careers_page"):
            self.assertIn(field, body["edited_fields"])

    def test_admin_rejects_invalid_website(self):
        response = self.send("PATCH", f"/admin/companies/{COMPANY_ID}", token="admin-token", json={"website": "not a url"})
        self.assertEqual(response.status_code, 422)

    def test_delete_remembers_source(self):
        self.assertEqual(self.send("DELETE", f"/admin/companies/{COMPANY_ID}", token="admin-token").status_code, 204)
        tombstone = self.db.of("POST", "company_tombstones")[0][3]
        self.assertEqual(tombstone[0]["source_key"], "sec-cik:abc")
        self.assertEqual(len(self.db.of("DELETE", "startup_companies")), 1)

    def test_notes(self):
        saved = self.send("PUT", f"/companies/{COMPANY_ID}/note", json={"note": "Ping the CTO"})
        self.assertEqual(saved.json()["note"], "Ping the CTO")
        self.assertEqual(self.db.of("POST", "company_notes")[0][2], "company_id,user_id")
        cleared = self.send("PUT", f"/companies/{COMPANY_ID}/note", json={"note": "   "})
        self.assertEqual(cleared.json(), {"note": "", "updated_at": None})
        self.assertEqual(len(self.db.of("DELETE", "company_notes")), 1)

    def test_view_toggle(self):
        self.send("PUT", f"/companies/{COMPANY_ID}/view", json={"viewed": True})
        self.send("PUT", f"/companies/{COMPANY_ID}/view", json={"viewed": False})
        first, second = [call[3] for call in self.db.of("POST", "company_views")]
        self.assertTrue(first["viewed"] and first["viewed_at"])
        self.assertEqual((second["viewed"], second["viewed_at"]), (False, None))
        self.assertEqual(first["user_id"], USER_ID)

    def test_detail_includes_personal_state(self):
        body = self.get(f"/companies/{COMPANY_ID}").json()
        self.assertEqual((body["name"], body["note"], body["viewed"]), ("Acme", "", False))

    def test_invalid_company_id(self):
        self.assertEqual(self.get("/companies/not-a-uuid").status_code, 404)

    def test_export_csv(self):
        response = self.get("/companies/export", params={"careers": "yes"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers["content-type"])
        lines = response.text.lstrip("﻿").splitlines()
        self.assertTrue(lines[0].startswith("Company,Website,Careers page"))
        self.assertIn("Acme,https://acme.com", lines[1])
        self.assertIn("Ping CTO", lines[1])
        self.assertIn("Investors", lines[0])
        self.assertIn("Accel; Sequoia", lines[1])  # lists are readable, not Python reprs
        self.assertIn("hello@acme.com", lines[1])

    def test_cannot_demote_self(self):
        response = self.send("PATCH", f"/admin/users/{ADMIN_ID}/role", token="admin-token", json={"role": "user"})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
