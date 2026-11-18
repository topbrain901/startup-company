import unittest

from startup_scraper.careers import CareersDetector, careers_links, find_ats
from startup_scraper.discovery import CompanyProfile, candidate_labels, score_page
from startup_scraper.founding import FoundedFact, best, from_structured_data, from_text
from startup_scraper.http import FetchResult
from startup_scraper.page import PageInfo, looks_parked
from startup_scraper.sources.rss import _company_name
from startup_scraper.util import (
    batch_year,
    classify_entity,
    core_name,
    normalize_country,
    registrable_domain,
    smart_title,
    split_location,
)


def page(html: str, url: str = "https://www.acme.com/") -> PageInfo:
    return PageInfo.parse(url, html)


class FakeClient:
    """WebClient stand-in serving canned pages."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def fetch(self, url, **kwargs):
        if url in self.pages:
            return FetchResult(url=url, status=200, content_type="text/html", body=self.pages[url].encode())
        return FetchResult(url=url, status=404, error="HTTP 404")

    def fetch_json(self, url, **kwargs):
        return None


class NormalizationTests(unittest.TestCase):
    def test_headline_names(self):
        self.assertEqual(_company_name("Finnish healthtech Treat raises €3M to tackle inefficiencies"), "Treat")
        self.assertEqual(_company_name("AI inference startup Daisytuner raises €6M seed"), "Daisytuner")
        self.assertEqual(_company_name("Tiberius Aerospace with strong UK links raises $85 million"), "Tiberius Aerospace")
        self.assertEqual(_company_name("London-based Acme Robotics secures £2M"), "Acme Robotics")
        self.assertEqual(_company_name("dbt Labs raises $222M"), "dbt Labs")
        self.assertEqual(_company_name("The Browser Company raises $50M"), "The Browser Company")

    def test_locations(self):
        self.assertEqual(
            split_location("San Francisco, CA, USA; Remote"),
            {"city": "San Francisco", "state": "California", "country": "United States", "is_remote": True},
        )
        self.assertEqual(split_location("Bengaluru, KA, India")["state"], "KA")
        self.assertEqual(split_location("India")["country"], "India")
        self.assertEqual(split_location("London")["city"], "London")
        self.assertEqual(normalize_country("USA; Remote"), "United States")
        self.assertEqual(normalize_country("UNITED KINGDOM"), "United Kingdom")
        self.assertEqual(smart_title("NEW YORK"), "New York")
        self.assertEqual(smart_title("San Francisco"), "San Francisco")

    def test_batch_year(self):
        self.assertEqual(batch_year("Summer 2009"), 2009)
        self.assertEqual(batch_year("W24"), 2024)
        self.assertIsNone(batch_year(None))

    def test_entity_kind(self):
        self.assertEqual(classify_entity("Southview Timberland Fund LLC", "Pooled Investment Fund", "SEC EDGAR Form D"), "investment_vehicle")
        self.assertEqual(classify_entity("Acme Capital Partners II, L.P.", "Other", "SEC EDGAR Form D"), "investment_vehicle")
        self.assertEqual(classify_entity("Maple Apartments LLC", "Residential", "SEC EDGAR Form D"), "real_estate")
        self.assertEqual(classify_entity("Huxley Medical, Inc.", "Other Health Care", "SEC EDGAR Form D"), "startup")
        self.assertEqual(classify_entity("Anything Fund", None, "Y Combinator directory"), "startup")

    def test_names_and_domains(self):
        self.assertEqual(core_name("Huxley Medical, Inc."), "huxley medical")
        self.assertEqual(core_name("Acme Corp d/b/a Rocket"), "acme")
        self.assertEqual(registrable_domain("https://jobs.acme.co.uk/x"), "acme.co.uk")
        labels = candidate_labels(CompanyProfile("Huxley Medical, Inc."))
        self.assertEqual(labels[:2], ["huxleymedical", "huxleymed"])
        self.assertIn("gettreat", candidate_labels(CompanyProfile("Treat")))


class VerificationTests(unittest.TestCase):
    def test_matching_homepage_scores_high(self):
        company = CompanyProfile("Huxley Medical, Inc.", city="Atlanta")
        home = page(
            "<title>Huxley Medical | Wearable sleep diagnostics</title><h1>Sleep testing, simplified</h1>"
            "<p>Based in Atlanta, Georgia.</p>" + "<a href='/a'>a</a>" * 5,
            "https://huxleymed.com/",
        )
        self.assertGreaterEqual(score_page(company, "https://huxleymed.com/", home), 5)

    def test_namesake_scores_low(self):
        company = CompanyProfile("Huxley Medical, Inc.")
        other = page("<title>Huxley | Recruitment agency</title><p>We place engineers.</p>" + "<a href='/a'>a</a>" * 5, "https://huxley.com/")
        self.assertLess(score_page(company, "https://huxley.com/", other), 4)

    def test_weak_name_needs_context(self):
        company = CompanyProfile("Treat", description="Software that reduces paperwork for private healthcare clinics")
        unrelated = page("<title>Treat</title><p>Gourmet dog biscuits delivered.</p>" + "<a href='/a'>a</a>" * 5, "https://treat.com/")
        self.assertLessEqual(score_page(company, "https://treat.com/", unrelated), 3)

    def test_parked_domain(self):
        self.assertTrue(looks_parked(page("<title>acme.io</title><p>This domain is for sale! Make an offer.</p>")))
        self.assertLess(score_page(CompanyProfile("Acme"), "https://acme.io/", page("<title>Acme</title><p>Buy this domain</p>")), 0)


class CareersTests(unittest.TestCase):
    def test_ats_detection(self):
        self.assertEqual(find_ats('<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>')[:2], ("greenhouse", "acme"))
        self.assertEqual(find_ats('<a href="https://jobs.lever.co/acme-inc">Jobs</a>')[:2], ("lever", "acme-inc"))
        self.assertEqual(find_ats('<a href="https://jobs.ashbyhq.com/trajectory">Open roles</a>')[:2], ("ashby", "trajectory"))
        self.assertIsNone(find_ats("<p>No jobs here</p>"))

    def test_careers_links(self):
        home = page(
            '<a href="/about">About</a><a href="/careers">Careers</a><a href="/blog/jobs-to-be-done">JTBD</a>'
            '<a href="https://twitter.com/acme">Twitter</a><a href="/#join">Join us</a>'
        )
        links = careers_links(home)
        self.assertEqual(links[0], ("https://www.acme.com/careers", True))
        self.assertNotIn("https://www.acme.com/blog/jobs-to-be-done", [url for url, _ in links])

    def test_detect_website_careers_page(self):
        home_html = '<title>Acme</title><a href="/careers">Careers</a>'
        client = FakeClient({
            "https://www.acme.com/careers": "<title>Careers at Acme</title><h1>Join our team</h1><p>Open roles</p>",
        })
        result = CareersDetector(client).detect(page(home_html))
        self.assertTrue(result.has_careers_page)
        self.assertEqual(result.careers_url, "https://www.acme.com/careers")
        self.assertEqual(result.provider, "website")

    def test_detect_no_careers(self):
        client = FakeClient({})
        result = CareersDetector(client).detect(page("<title>Acme</title><a href='/about'>About</a>"))
        self.assertFalse(result.has_careers_page)


class FoundingTests(unittest.TestCase):
    def test_structured_data(self):
        info = page('<script type="application/ld+json">{"@graph":[{"@type":"Organization","foundingDate":"2019-04-02"}]}</script>')
        fact = from_structured_data(info)
        self.assertEqual((fact.year, fact.on, fact.source), (2019, "2019-04-02", "website_structured_data"))

    def test_text_patterns(self):
        self.assertEqual(from_text(page("<p>Founded in 2016 by two engineers.</p>")).year, 2016)
        self.assertEqual(from_text(page("<p>Est. 1998</p>")).year, 1998)
        self.assertEqual(from_text(page("<p>In 2015, we founded the company.</p>")).year, 2015)
        copyright_fact = from_text(page("<footer>© 2014–2026 Acme Inc.</footer>"))
        self.assertEqual((copyright_fact.year, copyright_fact.source), (2014, "website_copyright"))
        self.assertIsNone(from_text(page("<p>Launched a new product in 2024.</p>")))

    def test_rank_order(self):
        chosen = best(FoundedFact(2020, "domain_registration"), FoundedFact(2018, "yc_profile"), None)
        self.assertEqual(chosen.source, "yc_profile")


if __name__ == "__main__":
    unittest.main()
