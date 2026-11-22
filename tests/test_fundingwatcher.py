import unittest
from datetime import date

from startup_scraper.sources.fundingwatcher import PAGES, employees, investors, money, parse_page, to_models

PAGE = """
<table><tr><th>Company</th><th>Person</th><th>Title</th><th>Verified email</th></tr>
  <tr><td><a href="https://acme.com">Acme</a></td><td>Jane Doe</td><td>CEO</td><td>jane@acme.com</td></tr></table>
<table>
<tr><th>Company</th><th>What they do</th><th>Sector</th><th>Location</th><th>Last round</th><th class="n">Amount</th>
    <th class="n">Date</th><th class="n">Total raised</th><th>Investors</th><th>Employees</th><th class="n">Founded</th></tr>
<tr><td class="co"><a href="https://www.lightframe.tech/" rel="nofollow noopener">Light Frame</a></td>
    <td class="dim what">Light Frame builds core banking technology for wealth managers.</td><td>Fintech</td>
    <td>Providence, United States</td><td>Seed</td><td class="n">$5.1M</td><td class="n">2026-11-10</td>
    <td class="n">$6.8M</td><td>Half Court Ventures, ATX Venture Partners +2</td><td>1 to 10</td><td>2024</td></tr>
<tr><td class="co"><a href="https://mistral.ai">Mistral AI</a> <span class="badge">Unicorn</span></td>
    <td>Mistral AI develops AI models.</td><td>Artificial intelligence</td><td>Paris, France</td><td>Series D</td>
    <td>$3.5B</td><td>2026-09-08</td><td>$7.5B</td><td>Andreessen Horowitz</td><td>1,001 to 5,000</td><td>2023</td></tr>
</table>
"""


class FundingWatcherTests(unittest.TestCase):
    def test_values(self):
        self.assertEqual((money("$107K"), money("$5.1M"), money("$3.5B"), money("—")), (107_000, 5_100_000, 3.5e9, None))
        self.assertEqual(employees("1,001 to 5,000"), (1001, "1,001–5,000"))
        self.assertEqual(employees("5,001+"), (5001, "5,001+"))
        self.assertEqual(investors("A, B, C +2"), (["A", "B", "C"], 2))

    def test_rows_become_companies_and_rounds(self):
        records = list(parse_page(PAGE, PAGES[0]))
        self.assertEqual([record["company"] for record in records], ["Light Frame", "Mistral AI"])  # contacts table skipped
        company, funding = to_models(records[0])
        self.assertEqual((company.website, company.domain), ("https://www.lightframe.tech/", "lightframe.tech"))
        self.assertEqual((company.city, company.country, company.industry), ("Providence", "United States", "Fintech"))
        self.assertEqual((company.founded_year, company.founded_source, company.employee_count), (2024, "fundingwatcher", 1))
        self.assertEqual(company.metadata["employees_range"], "1–10")
        self.assertEqual((funding.round_type, funding.amount_usd, funding.announced_on), ("Seed", 5_100_000, date(2026, 11, 10)))
        self.assertEqual(funding.investors, ["Half Court Ventures", "ATX Venture Partners"])
        self.assertEqual((funding.metadata["more_investors"], funding.metadata["total_raised_usd"]), (2, 6_800_000))
        self.assertEqual(company.source_url, PAGES[0])  # attribution back to the list page

    def test_only_a_few_list_pages_are_read(self):
        self.assertLessEqual(len(PAGES), 8)
        self.assertTrue(all(page.startswith("https://fundingwatcher.com/") for page in PAGES))


if __name__ == "__main__":
    unittest.main()
