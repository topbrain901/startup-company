import unittest

from startup_scraper.supabase import SupabaseStore
from startup_scraper.sources.rss import FUND_MANAGER_RE, _amount, _company_name, _investors
from startup_scraper.util import domain_from_url, normalize_name


class ParsingTests(unittest.TestCase):
    def test_amounts(self):
        self.assertEqual(_amount("Acme raises $12.5 million"), (12_500_000, "USD"))
        self.assertEqual(_amount("Acme secures €3m"), (3_000_000, "EUR"))
        self.assertEqual(_amount("Acme hits $1.5B valuation with $250M raise"), (250_000_000, "USD"))
        self.assertEqual(_amount("Acme"), (None, None))

    def test_company_name(self):
        self.assertEqual(_company_name("Acme raises $5M seed round"), "Acme")
        self.assertEqual(_company_name("Funding news: Bright AI secures £2 million"), "Bright AI")
        self.assertEqual(_company_name("Model ML hits $1.5B valuation with $250M raise"), "Model ML")

    def test_investors(self):
        self.assertEqual(
            _investors("The round was led by Peak Ventures, with participation from North Fund and ACME Capital."),
            ["Peak Ventures", "North Fund", "ACME Capital"],
        )

    def test_fund_manager_headlines(self):
        self.assertIsNotNone(FUND_MANAGER_RE.search("Proximal Ventures raises debut fund to back startups"))
        self.assertIsNone(FUND_MANAGER_RE.search("Trajectory raises $45M for AI training"))

    def test_normalization(self):
        self.assertEqual(normalize_name("Café Labs, Inc."), "cafe labs inc")
        self.assertEqual(domain_from_url("https://www.example.com/a"), "example.com")

    def test_anon_key_is_rejected_before_network_request(self):
        header = base64_url({"alg": "HS256", "typ": "JWT"})
        payload = base64_url({"role": "anon"})
        store = SupabaseStore("https://example.supabase.co", f"{header}.{payload}.signature")
        with self.assertRaisesRegex(RuntimeError, "anon/publishable"):
            store.check_schema()


def base64_url(value):
    import base64
    import json

    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


if __name__ == "__main__":
    unittest.main()

