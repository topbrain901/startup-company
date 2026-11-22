"""Fields added after comparing with webcodelabb/startup-scraper: valuation, investors, news location,
social profiles, and a contact email."""

import unittest

from startup_scraper.contacts import contact_email, contacts_from_page, github_url, linkedin_url, twitter_url
from startup_scraper.enrichment import Enricher
from startup_scraper.http import FetchResult
from startup_scraper.models import FundingRound
from startup_scraper.page import PageInfo
from startup_scraper.places import place_from_news
from startup_scraper.sources.rss import _amount, _investors, _valuation


def page(html: str, url: str = "https://www.acme.com/") -> PageInfo:
    return PageInfo.parse(url, html)


class FakeClient:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.requested: list[str] = []

    def fetch(self, url, **kwargs):
        self.requested.append(url)
        if url in self.pages:
            return FetchResult(url=url, status=200, content_type="text/html", body=self.pages[url].encode())
        return FetchResult(url=url, status=404, error="HTTP 404")

    def fetch_json(self, url, **kwargs):
        return None


class ValuationTests(unittest.TestCase):
    def test_valuation_is_not_the_round_size(self):
        text = "Acme raises $50M Series B at a $1.2 billion valuation"
        self.assertEqual(_amount(text), (50_000_000, "USD"))
        self.assertEqual(_valuation(text), (1_200_000_000, "USD"))

    def test_valued_at_phrases(self):
        self.assertEqual(_valuation("The deal values it at... Acme is now valued at about €400M."), (400_000_000, "EUR"))
        self.assertEqual(_valuation("raised $20M at a valuation of $150 million"), (150_000_000, "USD"))
        self.assertEqual(_valuation("Acme hits $3B valuation with $200M raise"), (3_000_000_000, "USD"))
        self.assertEqual(_valuation("Acme raises $10M; valuation undisclosed"), (None, None))

    def test_round_model_carries_valuation(self):
        row = FundingRound(source_key="r", company_source_key="c", source_name="x", source_url="u",
                           valuation=1e9, valuation_currency="USD", valuation_usd=1e9).row()
        self.assertEqual((row["valuation"], row["valuation_usd"]), (1e9, 1e9))


class InvestorTests(unittest.TestCase):
    def test_lead_and_participants(self):
        self.assertEqual(
            _investors("The round was led by Sequoia Capital, with participation from Accel and Index Ventures."),
            ["Sequoia Capital", "Accel", "Index Ventures"],
        )

    def test_raised_from_does_not_skip_the_lead(self):
        self.assertEqual(
            _investors("Acme has raised a $5M round led by Sequoia, with participation from Accel."), ["Sequoia", "Accel"]
        )
        # Feed text with a missing space and a truncated tail.
        self.assertEqual(
            _investors("Dcubed has raised a round led byWarsaw Equity Group (WEG), with participation from the EIC Fund, the HTGF Opport..."),
            ["Warsaw Equity Group (WEG)", "EIC Fund"],
        )

    def test_more_phrasings(self):
        self.assertEqual(_investors("Acme lands $10M from Y Combinator and General Catalyst."), ["Y Combinator", "General Catalyst"])
        self.assertEqual(_investors("It was co-led by a16z and Lightspeed, which previously backed it."), ["a16z", "Lightspeed"])
        self.assertEqual(
            _investors("Existing investors Index Ventures and Balderton also participated."), ["Index Ventures", "Balderton"]
        )
        self.assertEqual(_investors("Backed by London-based Balderton in 2021 and angel investors."), ["Balderton"])

    def test_generic_phrases_are_not_investors(self):
        self.assertEqual(_investors("Acme raised the money from its existing investors and others."), [])
        self.assertEqual(_investors("Acme raises $5M from undisclosed investors."), [])


class NewsLocationTests(unittest.TestCase):
    def test_hyphen_based(self):
        place = place_from_news("Berlin-based Acme raises $50M", "", "Acme")
        self.assertEqual((place["city"], place["country"], place["location"]), ("Berlin", "Germany", "Berlin, Germany"))

    def test_us_city_gets_state(self):
        place = place_from_news("Acme raises $5M", "Acme, a San Francisco-based startup, builds robots.", "Acme")
        self.assertEqual((place["city"], place["state"], place["country"]), ("San Francisco", "California", "United States"))

    def test_based_in(self):
        place = place_from_news("Payflow secures $5M", "Payflow, headquartered in Austin, Texas, sells software.", "Payflow")
        self.assertEqual(place["location"], "Austin, Texas, United States")

    def test_leading_demonym(self):
        self.assertEqual(place_from_news("Finnish healthtech Treat raises €3M", "", "Treat")["country"], "Finland")
        self.assertEqual(place_from_news("French AI startup Mistral raises $600M", "", "Mistral")["country"], "France")

    def test_nationality_next_to_name_in_summary(self):
        self.assertEqual(place_from_news("Dcubed raises €27M", "German spacetech company Dcubed has raised a round.", "Dcubed")["country"], "Germany")
        self.assertIsNone(place_from_news("Acme raises $5M", "The German investor backed several startups, including Acme.", "Acme"))

    def test_investor_location_is_ignored(self):
        summary = "The round was led by London-based Balderton, which has backed dozens of startups across Europe and beyond."
        self.assertIsNone(place_from_news("Acme raises $5M", summary, "Acme"))

    def test_words_that_are_not_places(self):
        self.assertIsNone(place_from_news("AI-based CloudCo raises $2M", "CloudCo builds Cloud-based tools.", "CloudCo"))
        self.assertIsNone(place_from_news("American Express invests in Acme", "", "American Express"))


class ProfileLinkTests(unittest.TestCase):
    def test_canonical_urls(self):
        self.assertEqual(linkedin_url("https://uk.linkedin.com/company/acme/?trk=x"), "https://www.linkedin.com/company/acme")
        self.assertEqual(linkedin_url("linkedin.com/company/acme"), "https://www.linkedin.com/company/acme")
        self.assertIsNone(linkedin_url("https://www.linkedin.com/in/jane-doe"))  # personal profiles are skipped
        self.assertEqual(twitter_url("https://twitter.com/acmehq?lang=en"), "https://x.com/acmehq")
        self.assertEqual(twitter_url("@acmehq"), "https://x.com/acmehq")
        self.assertIsNone(twitter_url("https://twitter.com/intent/tweet?text=hi"))
        self.assertIsNone(twitter_url("https://x.com/acmehq/status/123"))
        self.assertEqual(github_url("https://github.com/orgs/acme/people"), "https://github.com/acme")
        self.assertIsNone(github_url("https://github.com/features"))

    def test_footer_links(self):
        site = page("""<html><body>
          <a href="https://www.linkedin.com/company/acme-robotics/">LinkedIn</a>
          <a href="https://twitter.com/acmerobotics">Twitter</a>
          <a href="https://github.com/acme-robotics">GitHub</a>
          <a href="https://twitter.com/share?url=x">Share</a>
        </body></html>""")
        found = contacts_from_page(site, "https://www.acme.com/", "Acme Robotics")
        self.assertEqual(found.linkedin_url, "https://www.linkedin.com/company/acme-robotics")
        self.assertEqual(found.twitter_url, "https://x.com/acmerobotics")
        self.assertEqual(found.github_url, "https://github.com/acme-robotics")

    def test_profiles_inside_page_data(self):
        site = page("""<html><body><div id="root"></div><script>
          window.__DATA__ = {"footer": [{"url": "https:\\/\\/twitter.com\\/PostHog"}, {"url": "linkedin.com/company/posthog"},
            {"url": "https://github.com/PostHog/posthog"}, {"url": "https://twitter.com/someinvestor"}]}
        </script></body></html>""", "https://posthog.com/")
        found = contacts_from_page(site, "https://posthog.com/", "PostHog")
        self.assertEqual(
            (found.linkedin_url, found.twitter_url, found.github_url),
            ("https://www.linkedin.com/company/posthog", "https://x.com/PostHog", "https://github.com/PostHog"),
        )
        # In page data a lone profile that is not named like the company is not trusted.
        other = page('<script>{"u": "https://twitter.com/someinvestor"}</script>', "https://posthog.com/")
        self.assertIsNone(contacts_from_page(other, "https://posthog.com/", "PostHog").twitter_url)

    def test_ambiguous_profiles_are_skipped(self):
        site = page('<a href="https://twitter.com/partnerone">a</a><a href="https://twitter.com/partnertwo">b</a>')
        self.assertIsNone(contacts_from_page(site, "https://www.acme.com/", "Acme").twitter_url)
        site = page('<a href="https://twitter.com/partnerone">a</a><a href="https://twitter.com/acme">b</a>')
        self.assertEqual(contacts_from_page(site, "https://www.acme.com/", "Acme").twitter_url, "https://x.com/acme")


class ContactEmailTests(unittest.TestCase):
    def test_role_address_on_own_domain(self):
        site = page("""<a href="mailto:jane.doe@acme.com">Jane</a> <a href="mailto:hello@acme.com?subject=Hi">Say hi</a>
                       <p>Jobs: careers@acme.com</p> <a href="mailto:support@wix.com">Built with Wix</a>""")
        self.assertEqual(contact_email(site, "https://www.acme.com/"), "careers@acme.com")

    def test_personal_addresses_are_never_collected(self):
        site = page('<a href="mailto:jane.doe@acme.com">Jane</a><p>Write to bob@acme.com</p>')
        self.assertIsNone(contact_email(site, "https://www.acme.com/"))

    def test_cloudflare_obfuscated_email(self):
        key = 0x42
        encoded = format(key, "02x") + "".join(format(ord(char) ^ key, "02x") for char in "info@acme.com")
        site = page(f'<a href="/cdn-cgi/l/email-protection#{encoded}">[email protected]</a>')
        self.assertEqual(contact_email(site, "https://www.acme.com/"), "info@acme.com")


class EnricherContactsTests(unittest.TestCase):
    def test_enrichment_patch_includes_links_and_respects_edits(self):
        home = """<html><head><title>Acme - payroll software</title></head><body><h1>Acme</h1>
          <p>Acme builds payroll software for restaurants.</p>
          <a href="https://www.linkedin.com/company/acme/">LinkedIn</a>
          <a href="https://www.acme.com/contact">Contact</a></body></html>"""
        contact = '<html><body><a href="mailto:hello@acme.com">hello@acme.com</a></body></html>'
        client = FakeClient({"https://www.acme.com/": home, "https://www.acme.com/contact": contact})
        enricher = Enricher(client=client, budget_seconds=30)
        row = {
            "id": "c1", "name": "Acme", "website": "https://www.acme.com/", "description": "Payroll software",
            "source_name": "Manual entry", "source_url": "", "entity_kind": "real_estate",  # skips Wikidata lookups
            "edited_fields": [], "metadata": {},
        }
        result = enricher.enrich(row)
        self.assertIsNone(result.error)
        self.assertEqual(result.patch["linkedin_url"], "https://www.linkedin.com/company/acme")
        self.assertEqual(result.patch["contact_email"], "hello@acme.com")
        self.assertTrue(result.contacts_found)

        edited = enricher.enrich({**row, "edited_fields": ["contact_email"], "contact_email": "jobs@acme.com"})
        self.assertNotIn("contact_email", edited.patch)


if __name__ == "__main__":
    unittest.main()
