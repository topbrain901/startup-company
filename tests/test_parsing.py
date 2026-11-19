import unittest

from startup_scraper.models import Company, FundingRound
from startup_scraper.stage_filter import detected_types, filter_by_stage_types
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

    def test_early_stage_filter_uses_explicit_evidence(self):
        pre_seed = Company(
            source_key="company:preseed", source_name="News", source_id="1", source_url="https://news.test/1",
            name="Acme", normalized_name="acme", description="Acme is raising a friends and family round.",
        )
        unknown = Company(
            source_key="company:unknown", source_name="SEC", source_id="2", source_url="https://sec.test/2",
            name="Later Co", normalized_name="later co", status="Fundraising",
        )
        round_one = FundingRound(
            source_key="round:1", company_source_key=pre_seed.source_key, source_name="News",
            source_url="https://news.test/1", round_type="Angel funding",
        )
        round_two = FundingRound(
            source_key="round:2", company_source_key=unknown.source_key, source_name="SEC",
            source_url="https://sec.test/2", round_type="Regulation D exempt offering",
        )
        companies, rounds = filter_by_stage_types([pre_seed, unknown], [round_one, round_two], ["pre-seed"])
        self.assertEqual([item.source_key for item in companies], [pre_seed.source_key])
        self.assertEqual([item.source_key for item in rounds], [round_one.source_key])
        self.assertEqual(detected_types(pre_seed, round_one), {"pre-seed"})

    def test_self_funded_and_bootstrapped_are_separate_options(self):
        company = Company(
            source_key="company:boot", source_name="YC", source_id="3", source_url="https://yc.test/3",
            name="Tiny Co", normalized_name="tiny co", description="A bootstrapped, self-funded company.",
        )
        self.assertEqual(detected_types(company), {"bootstrapped", "self-funded"})


def base64_url(value):
    import base64
    import json

    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


if __name__ == "__main__":
    unittest.main()

