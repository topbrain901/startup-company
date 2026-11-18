from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date
from typing import Iterable

from ..http import HttpClient
from ..models import Company, FundingRound
from ..util import (
    US_STATES,
    RateLimiter,
    classify_entity,
    normalize_country,
    normalize_name,
    number,
    smart_title,
    stable_key,
)


DATASET_PAGE = "https://www.sec.gov/data-research/sec-markets-data/form-d-data-sets"
ZIP_RE = re.compile(r'href=["\'](?P<url>[^"\']+(?P<quarter>20\d{2})q(?P<q>[1-4])_d\.zip)["\']', re.I)


def discover_quarters(client: HttpClient) -> list[tuple[str, str]]:
    html = client.request(DATASET_PAGE).decode("utf-8", "replace")
    found: dict[str, str] = {}
    for match in ZIP_RE.finditer(html):
        key = f"{match.group('quarter')}Q{match.group('q')}"
        url = match.group("url")
        if url.startswith("/"):
            url = "https://www.sec.gov" + url
        found[key] = url
    return sorted(found.items(), reverse=True)


def _tsv(zf: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    name = next(name for name in zf.namelist() if name.upper().endswith(suffix.upper()))
    with zf.open(name) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
        return list(csv.DictReader(text, delimiter="\t"))


def _is_true(value: str | None) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _filing_url(cik: str, accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{accession}-index.html"


def collect(
    client: HttpClient,
    *,
    quarter_count: int = 1,
    limit: int | None = None,
    include_funds: bool = False,
) -> Iterable[tuple[Company, FundingRound]]:
    quarters = discover_quarters(client)[:quarter_count]
    emitted = 0
    limiter = RateLimiter(2)
    for quarter, url in quarters:
        limiter.wait()
        archive = io.BytesIO(client.request(url))
        with zipfile.ZipFile(archive) as zf:
            submissions = {row["ACCESSIONNUMBER"]: row for row in _tsv(zf, "FORMDSUBMISSION.tsv")}
            offerings = {row["ACCESSIONNUMBER"]: row for row in _tsv(zf, "OFFERING.tsv")}
            issuers = [row for row in _tsv(zf, "ISSUERS.tsv") if _is_true(row.get("IS_PRIMARYISSUER_FLAG"))]
        for issuer in issuers:
            accession = issuer["ACCESSIONNUMBER"]
            offering = offerings.get(accession)
            submission = submissions.get(accession)
            if not offering or not submission:
                continue
            if not include_funds and (
                (offering.get("INDUSTRYGROUPTYPE") or "").strip().lower() == "pooled investment fund"
                or _is_true(offering.get("ISPOOLEDINVESTMENTFUNDTYPE"))
            ):
                continue
            amount_sold = number(offering.get("TOTALAMOUNTSOLD"))
            if amount_sold is None or amount_sold <= 0:
                continue
            name = (issuer.get("ENTITYNAME") or "").strip()
            cik = (issuer.get("CIK") or "").strip()
            if not name or not cik:
                continue
            url = _filing_url(cik, accession)
            company_key = stable_key("sec-cik", cik)
            sale_date = offering.get("SALE_DATE") or None
            announced_on = None
            for raw_date in (submission.get("FILING_DATE"), sale_date):
                if raw_date:
                    try:
                        announced_on = date.fromisoformat(raw_date)
                        break
                    except ValueError:
                        pass
            city = smart_title(issuer.get("CITY") or None)
            state_code = (issuer.get("STATEORCOUNTRY") or "").strip().upper()
            region = smart_title(issuer.get("STATEORCOUNTRYDESCRIPTION") or None) or state_code or None
            if state_code in US_STATES:
                state, country = US_STATES[state_code], "United States"
            else:
                state, country = None, normalize_country(region)
            location = ", ".join(part for part in (city, state or country) if part)
            founded_year = None
            raw_founded_year = (issuer.get("YEAROFINC_VALUE_ENTERED") or "").strip()
            if raw_founded_year.isdigit() and 1800 <= int(raw_founded_year) <= date.today().year:
                founded_year = int(raw_founded_year)
            industry = offering.get("INDUSTRYGROUPTYPE") or None
            previous_names = [
                issuer.get(column) for column in (
                    "ISSUER_PREVIOUSNAME_1", "ISSUER_PREVIOUSNAME_2", "ISSUER_PREVIOUSNAME_3",
                    "EDGAR_PREVIOUSNAME_1", "EDGAR_PREVIOUSNAME_2", "EDGAR_PREVIOUSNAME_3",
                )
                if issuer.get(column) and issuer.get(column, "").strip().lower() not in {"none", "n/a"}
            ]
            company = Company(
                source_key=company_key,
                source_name="SEC EDGAR Form D",
                source_id=cik,
                source_url=url,
                name=name,
                normalized_name=normalize_name(name),
                city=city,
                state=state,
                country=country,
                location=location or None,
                industry=industry,
                entity_kind=classify_entity(name, industry, "SEC EDGAR Form D"),
                founded_year=founded_year,
                founded_source="sec_form_d" if founded_year else None,
                status="Fundraising",
                metadata={
                    "cik": cik,
                    "entity_type": issuer.get("ENTITYTYPE") or None,
                    "jurisdiction_of_incorporation": issuer.get("JURISDICTIONOFINC") or None,
                    "year_of_incorporation_range": issuer.get("YEAROFINC_TIMESPAN_CHOICE") or None,
                    "previous_names": previous_names,
                    "revenue_range": offering.get("REVENUERANGE") or None,
                    "latest_accession": accession,
                },
            )
            securities = []
            for column, label in (
                ("ISEQUITYTYPE", "Equity"), ("ISDEBTTYPE", "Debt"),
                ("ISOPTIONTOACQUIRETYPE", "Option"), ("ISPOOLEDINVESTMENTFUNDTYPE", "Pooled investment fund"),
            ):
                if _is_true(offering.get(column)):
                    securities.append(label)
            funding = FundingRound(
                source_key=stable_key("sec-form-d", accession),
                company_source_key=company_key,
                source_name="SEC EDGAR Form D",
                source_url=url,
                announced_on=announced_on,
                round_type="Regulation D exempt offering",
                amount=amount_sold,
                currency="USD",
                amount_usd=amount_sold,
                title=f"{name} Form D {submission.get('SUBMISSIONTYPE', '')}".strip(),
                summary=f"Reported ${amount_sold:,.0f} sold in an exempt securities offering.",
                metadata={
                    "accession_number": accession,
                    "quarter": quarter,
                    "filing_type": submission.get("SUBMISSIONTYPE"),
                    "filing_date": submission.get("FILING_DATE"),
                    "first_sale_date": sale_date,
                    "is_amendment": _is_true(offering.get("ISAMENDMENT")),
                    "previous_accession": offering.get("PREVIOUSACCESSIONNUMBER") or None,
                    "total_offering_amount": number(offering.get("TOTALOFFERINGAMOUNT")),
                    "total_remaining": number(offering.get("TOTALREMAINING")),
                    "investor_count": number(offering.get("TOTALNUMBERALREADYINVESTED")),
                    "minimum_investment": number(offering.get("MINIMUMINVESTMENTACCEPTED")),
                    "securities": securities,
                    "exemptions": offering.get("FEDERALEXEMPTIONS_ITEMS_LIST") or None,
                },
            )
            yield company, funding
            emitted += 1
            if limit is not None and emitted >= limit:
                return

