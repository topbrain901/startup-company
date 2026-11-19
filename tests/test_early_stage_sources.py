import unittest

from startup_scraper.http import FetchResult
from startup_scraper.sources.early_stage import (
    antler,
    betalist,
    entrepreneur_first,
    product_hunt,
    techstars,
    wellfound,
)


class FakeClient:
    def __init__(self, body: str, content_type: str = "text/html"):
        self.body = body.encode()
        self.content_type = content_type

    def fetch(self, url, **kwargs):
        return FetchResult(url=url, status=200, content_type=self.content_type, body=self.body)


class EarlyStageSourceTests(unittest.TestCase):
    def test_product_hunt_atom(self):
        xml = """<feed xmlns="http://www.w3.org/2005/Atom"><entry>
          <id>tag:producthunt.test,2005:Post/12</id><published>2026-11-19T00:00:00Z</published>
          <link rel="alternate" href="https://www.producthunt.com/products/acme"/>
          <title>Acme</title><content type="html">Build faster with Acme</content>
        </entry></feed>"""
        rows = list(product_hunt(FakeClient(xml, "application/atom+xml"), None, lambda _: None))
        self.assertEqual((rows[0].name, rows[0].stage, rows[0].status), ("Acme", "Product launch", "Launched"))

    def test_betalist_prelaunch(self):
        html = """<div class="group startup-row"><a href="/startups/acme"></a>
          <span class="name">Acme</span><span class="tagline">An upcoming robot company</span></div>"""
        rows = list(betalist(FakeClient(html), 1, lambda _: None))
        self.assertEqual((rows[0].name, rows[0].stage), ("Acme", "Ideation"))

    def test_antler_portfolio(self):
        html = """<div class="portco_card">
          <p fs-cmsfilter-field="name">Acme</p><p fs-cmsfilter-field="description">Robots</p>
          <div fs-cmsfilter-field="location">UK</div><div fs-cmsfilter-field="location">DeepTech</div>
          <div fs-cmsfilter-field="location">2026</div>
          <a href="https://acme.test" class="clickable_link"></a></div>"""
        rows = list(antler(FakeClient(html), None, lambda _: None))
        self.assertEqual((rows[0].website, rows[0].stage, rows[0].founded_year), ("https://acme.test", "Pre-Seed", 2026))

    def test_entrepreneur_first_skips_featured_and_keeps_recent(self):
        html = """<div class="tile tile--company"><div data-companyname="Old" data-featured="true" data-companyslug="old"></div></div>
        <div class="tile tile--company"><div data-companyname="Acme" data-companyslug="acme"></div>
          <div class="tile__description">AI infrastructure</div><a class="locationtag">London</a>
          <a class="categorytag">Enterprise</a><div class="meta__row__name">Founded</div>
          <div class="meta__row__name">2026</div></div>"""
        rows = list(entrepreneur_first(FakeClient(html), 1, lambda _: None))
        self.assertEqual((rows[0].name, rows[0].stage, rows[0].country), ("Acme", "Pre-Seed", None))

    def test_techstars_website(self):
        html = """<p class="MuiTypography-h5">Acme</p><p class="MuiTypography-caption">2024</p>
          <p class="MuiTypography-body2">Climate software</p>
          <a href="https://acme.test/" aria-label="Website"></a>"""
        rows = list(techstars(FakeClient(html), None, lambda _: None))
        self.assertEqual((rows[0].name, rows[0].website, rows[0].founded_year), ("Acme", "https://acme.test/", 2024))

    def test_wellfound_directory(self):
        html = """<a href="/company/acme"><div class="text-lg lg:text-xl">Acme</div>
          <div class="line-clamp-2">Build robots</div><a href="/startups/industry/robotics">Robotics</a>
          <a href="/location/boston">Boston</a></a>"""
        rows = list(wellfound(FakeClient(html), 1, lambda _: None))
        self.assertEqual((rows[0].name, rows[0].industry, rows[0].city), ("Acme", "Robotics", "Boston"))


if __name__ == "__main__":
    unittest.main()
