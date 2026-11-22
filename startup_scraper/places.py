"""Company location from funding-news text ("Berlin-based Acme", "Acme, based in Austin", "Finnish healthtech Treat").

Only places in the gazetteer below are accepted: headline words such as "AI-based" or "Cloud-Based" look
like places to a pattern, and a wrong country is worse than none.
"""

from __future__ import annotations

import re

from .util import COUNTRY_ALIASES, KNOWN_COUNTRIES, US_STATES, normalize_name

US = "United States"
UK = "United Kingdom"

# city -> (country, US state or None)
_CITIES: dict[str, tuple[str, str | None]] = {}


def _add(country: str, names: str, state: str | None = None) -> None:
    for name in names.split("|"):
        _CITIES[normalize_name(name)] = (country, state)


for _state, _names in {
    "California": "San Francisco|SF|Palo Alto|Mountain View|Menlo Park|San Jose|Oakland|Berkeley|San Diego|"
                  "Los Angeles|LA|Santa Monica|Irvine|Sacramento|Sunnyvale|Redwood City|San Mateo|Santa Clara|Pasadena",
    "New York": "New York|New York City|NYC|Brooklyn|Manhattan",
    "Massachusetts": "Boston|Somerville",
    "Washington": "Seattle|Bellevue|Redmond",
    "Texas": "Austin|Dallas|Houston|San Antonio",
    "Illinois": "Chicago",
    "Colorado": "Denver|Boulder",
    "Florida": "Miami|Tampa|Orlando",
    "Georgia": "Atlanta",
    "District of Columbia": "Washington DC|Washington D.C.|DC|D.C.",
    "Oregon": "Portland",
    "Utah": "Salt Lake City|Lehi|Provo",
    "Arizona": "Phoenix|Scottsdale|Tempe",
    "Pennsylvania": "Pittsburgh|Philadelphia",
    "Michigan": "Detroit|Ann Arbor",
    "Minnesota": "Minneapolis",
    "Tennessee": "Nashville",
    "North Carolina": "Raleigh|Durham|Charlotte",
    "Ohio": "Columbus|Cincinnati|Cleveland",
    "Maryland": "Baltimore",
    "Missouri": "St. Louis|Kansas City",
    "Indiana": "Indianapolis",
    "Nevada": "Las Vegas",
    "New Jersey": "Hoboken|Jersey City|Princeton",
    "Wisconsin": "Madison|Milwaukee",
    "Idaho": "Boise",
}.items():
    _add(US, _names, _state)

for _country, _names in {
    "Canada": "Toronto|Vancouver|Montreal|Montréal|Ottawa|Calgary|Waterloo|Edmonton|Quebec City",
    UK: "London|Manchester|Edinburgh|Oxford|Bristol|Glasgow|Leeds|Belfast|Cardiff|Liverpool|Brighton|Sheffield|Nottingham",
    "France": "Paris|Lyon|Marseille|Toulouse|Nantes|Bordeaux|Lille|Grenoble|Montpellier",
    "Germany": "Berlin|Munich|Hamburg|Frankfurt|Cologne|Düsseldorf|Dusseldorf|Stuttgart|Leipzig|Dresden|Karlsruhe",
    "Netherlands": "Amsterdam|Rotterdam|Utrecht|The Hague|Eindhoven|Delft",
    "Belgium": "Brussels|Antwerp|Ghent|Leuven",
    "Switzerland": "Zurich|Zürich|Geneva|Lausanne|Basel|Zug",
    "Austria": "Vienna|Graz|Linz",
    "Sweden": "Stockholm|Gothenburg|Malmö|Malmo",
    "Norway": "Oslo|Bergen|Trondheim",
    "Denmark": "Copenhagen|Aarhus",
    "Finland": "Helsinki|Espoo|Tampere|Oulu",
    "Iceland": "Reykjavik",
    "Ireland": "Dublin|Cork|Galway",
    "Spain": "Madrid|Barcelona|Valencia|Seville|Malaga|Málaga|Bilbao",
    "Portugal": "Lisbon|Porto|Braga",
    "Italy": "Milan|Rome|Turin|Bologna|Florence|Naples",
    "Poland": "Warsaw|Krakow|Kraków|Wroclaw|Wrocław|Gdansk|Poznan",
    "Czech Republic": "Prague|Brno",
    "Slovakia": "Bratislava",
    "Hungary": "Budapest",
    "Romania": "Bucharest|Cluj-Napoca|Cluj",
    "Bulgaria": "Sofia",
    "Greece": "Athens|Thessaloniki",
    "Serbia": "Belgrade",
    "Croatia": "Zagreb",
    "Slovenia": "Ljubljana",
    "Estonia": "Tallinn|Tartu",
    "Latvia": "Riga",
    "Lithuania": "Vilnius|Kaunas",
    "Ukraine": "Kyiv|Kiev|Lviv|Kharkiv",
    "Turkey": "Istanbul|Ankara|Izmir",
    "Cyprus": "Nicosia|Limassol",
    "Israel": "Tel Aviv|Jerusalem|Haifa",
    "United Arab Emirates": "Dubai|Abu Dhabi",
    "Saudi Arabia": "Riyadh|Jeddah",
    "Qatar": "Doha",
    "Egypt": "Cairo",
    "Nigeria": "Lagos|Abuja",
    "Kenya": "Nairobi",
    "Ghana": "Accra",
    "Rwanda": "Kigali",
    "Uganda": "Kampala",
    "Ethiopia": "Addis Ababa",
    "Tanzania": "Dar es Salaam",
    "South Africa": "Cape Town|Johannesburg|Durban",
    "Morocco": "Casablanca",
    "Tunisia": "Tunis",
    "Jordan": "Amman",
    "Lebanon": "Beirut",
    "India": "Bengaluru|Bangalore|Mumbai|Delhi|New Delhi|Gurugram|Gurgaon|Noida|Hyderabad|Chennai|Pune|Kolkata|Ahmedabad|Jaipur",
    "Pakistan": "Karachi|Lahore|Islamabad",
    "Bangladesh": "Dhaka",
    "Sri Lanka": "Colombo",
    "Indonesia": "Jakarta",
    "Malaysia": "Kuala Lumpur",
    "Thailand": "Bangkok",
    "Vietnam": "Ho Chi Minh City|Hanoi",
    "Philippines": "Manila",
    "Japan": "Tokyo|Osaka|Kyoto",
    "South Korea": "Seoul|Busan",
    "China": "Beijing|Shanghai|Shenzhen|Hangzhou|Guangzhou",
    "Taiwan": "Taipei",
    "Australia": "Sydney|Melbourne|Brisbane|Perth|Adelaide|Canberra",
    "New Zealand": "Auckland|Wellington|Christchurch",
    "Brazil": "São Paulo|Sao Paulo|Rio de Janeiro|Belo Horizonte|Florianópolis|Curitiba",
    "Mexico": "Mexico City|Monterrey|Guadalajara",
    "Colombia": "Bogotá|Bogota|Medellín|Medellin",
    "Argentina": "Buenos Aires",
    "Chile": "Santiago",
    "Peru": "Lima",
    "Uruguay": "Montevideo",
    "Ecuador": "Quito",
}.items():
    _add(_country, _names)

# Regions that pin a state but not a city.
_REGIONS = {normalize_name(name): ("California", US) for name in ("Bay Area", "San Francisco Bay Area", "Silicon Valley")}
_STATES = {normalize_name(name): name for name in US_STATES.values() if name not in {"Georgia", "District of Columbia"}}
_COUNTRIES = {normalize_name(name): name for name in KNOWN_COUNTRIES} | {
    key: value for key, value in COUNTRY_ALIASES.items() if value in KNOWN_COUNTRIES
}

DEMONYMS = {
    "American": US, "British": UK, "English": UK, "Scottish": UK, "Welsh": UK, "Canadian": "Canada",
    "Mexican": "Mexico", "Brazilian": "Brazil", "Argentine": "Argentina", "Argentinian": "Argentina",
    "Chilean": "Chile", "Colombian": "Colombia", "Peruvian": "Peru", "Uruguayan": "Uruguay",
    "German": "Germany", "French": "France", "Spanish": "Spain", "Portuguese": "Portugal", "Italian": "Italy",
    "Dutch": "Netherlands", "Belgian": "Belgium", "Swiss": "Switzerland", "Austrian": "Austria",
    "Swedish": "Sweden", "Norwegian": "Norway", "Danish": "Denmark", "Finnish": "Finland",
    "Icelandic": "Iceland", "Irish": "Ireland", "Polish": "Poland", "Czech": "Czech Republic",
    "Estonian": "Estonia", "Latvian": "Latvia", "Lithuanian": "Lithuania", "Ukrainian": "Ukraine",
    "Romanian": "Romania", "Bulgarian": "Bulgaria", "Greek": "Greece", "Hungarian": "Hungary",
    "Croatian": "Croatia", "Serbian": "Serbia", "Turkish": "Turkey", "Israeli": "Israel",
    "Emirati": "United Arab Emirates", "Saudi": "Saudi Arabia", "Egyptian": "Egypt", "Nigerian": "Nigeria",
    "Kenyan": "Kenya", "Ghanaian": "Ghana", "Rwandan": "Rwanda", "Moroccan": "Morocco",
    "South African": "South Africa", "Indian": "India", "Pakistani": "Pakistan", "Bangladeshi": "Bangladesh",
    "Singaporean": "Singapore", "Indonesian": "Indonesia", "Malaysian": "Malaysia", "Thai": "Thailand",
    "Vietnamese": "Vietnam", "Filipino": "Philippines", "Japanese": "Japan", "Korean": "South Korea",
    "South Korean": "South Korea", "Chinese": "China", "Taiwanese": "Taiwan", "Australian": "Australia",
    "Luxembourgish": "Luxembourg", "Maltese": "Malta", "Cypriot": "Cyprus",
}

_DEMONYM_ALTERNATION = "|".join(sorted((re.escape(word) for word in DEMONYMS), key=len, reverse=True))
_WORD = r"[A-Z][\w.'’&-]*"
HYPHEN_BASED_RE = re.compile(rf"((?:{_WORD}\s+){{0,3}}{_WORD})-based\b")
BASED_IN_RE = re.compile(
    rf"\b(?:based|headquartered|located)\s+(?:out\s+of|in)\s+(?:the\s+)?((?:{_WORD})(?:[\s,]+{_WORD}){{0,3}})"
)
LEADING_PLACE_RE = re.compile(rf"^((?:{_WORD}\s+){{0,2}}{_WORD})\s+")


def lookup(phrase: str) -> dict[str, str | None] | None:
    """Exact gazetteer match for a place phrase."""
    phrase = re.sub(r"['’]s$", "", phrase.strip())  # "Sweden's Acme"
    key = normalize_name(phrase.replace("U.S.", "US").replace("U.K.", "UK"))
    if not key:
        return None
    if key in _CITIES:
        country, state = _CITIES[key]
        return {"city": phrase.strip(), "state": state, "country": country}
    if key in _REGIONS:
        state, country = _REGIONS[key]
        return {"city": None, "state": state, "country": country, "region": phrase.strip()}
    if key in _STATES:
        return {"city": None, "state": _STATES[key], "country": US}
    if key in _COUNTRIES:
        return {"city": None, "state": None, "country": _COUNTRIES[key]}
    return None


def _suffix_match(words: list[str]) -> dict[str, str | None] | None:
    """Longest trailing run of words that names a place ("The New York" -> New York)."""
    for start in range(len(words)):
        found = lookup(" ".join(words[start:]))
        if found:
            return found
    return None


def _prefix_match(words: list[str]) -> dict[str, str | None] | None:
    """Longest leading run of words that names a place ("Austin Texas" -> Austin, Texas)."""
    for end in range(len(words), 0, -1):
        found = lookup(" ".join(words[:end]))
        if found:
            rest = _prefix_match(words[end:]) if end < len(words) else None
            if rest and found.get("city") and rest["country"] == found["country"] and not rest.get("city"):
                found = {**found, "state": found.get("state") or rest.get("state")}
            return found
    return None


def _format(place: dict[str, str | None]) -> dict[str, str | None]:
    parts = [place.get("city") or place.get("region"), place.get("state"), place.get("country")]
    location = ", ".join(dict.fromkeys(part for part in parts if part))
    return {"city": place.get("city"), "state": place.get("state"), "country": place.get("country"), "location": location}


def _mentions(text: str, name: str, position: int, window: int) -> bool:
    lowered, target = text.lower(), name.lower()
    start, end = max(0, position - window), position + window
    return target in lowered[start:end]


def place_from_news(title: str, summary: str, company: str) -> dict[str, str | None] | None:
    """City/state/country for the company a funding headline is about, or None."""
    # 1. "Berlin-based Acme raises" / "Acme, a Berlin-based startup" in the headline.
    for match in HYPHEN_BASED_RE.finditer(title):
        found = _suffix_match(match.group(1).split())
        if found:
            return _format(found)
    # 2. The same phrases in the summary, but only next to the company's name: summaries also
    #    describe investors ("led by London-based Balderton").
    for match in HYPHEN_BASED_RE.finditer(summary):
        if _mentions(summary, company, match.start(), 80):
            found = _suffix_match(match.group(1).split())
            if found:
                return _format(found)
    for text in (title, summary):
        for match in BASED_IN_RE.finditer(text):
            if text is title or _mentions(text, company, match.start(), 100):
                found = _prefix_match(match.group(1).replace(",", " ").split())
                if found:
                    return _format(found)
    # 3. A nationality right before the name in the summary: "German spacetech company Dcubed".
    if company:
        match = re.search(rf"\b({_DEMONYM_ALTERNATION})\s+(?:[\w-]+\s+){{0,3}}?{re.escape(company)}\b", summary)
        if match:
            return _format({"country": DEMONYMS[match.group(1)]})
    # 4. A leading place or demonym that is not part of the name: "Finnish healthtech Treat", "London fintech Acme".
    headline = re.sub(r"^[^:]{2,35}:\s+", "", title).strip()
    match = LEADING_PLACE_RE.match(headline)
    if match and match.group(1).lower() not in company.lower():
        words = match.group(1).split()
        for end in range(len(words), 0, -1):
            phrase = " ".join(words[:end])
            if phrase in DEMONYMS:
                return _format({"country": DEMONYMS[phrase]})
            found = lookup(phrase)
            if found:
                return _format(found)
    return None
