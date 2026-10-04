"""Lead finder: business search plus an email lookup on each business's own website.

Two sources:
- OpenStreetMap (default): free, no key. Data (c) OpenStreetMap contributors, ODbL.
- Google Places API (New): needs a key, has better coverage and review counts.

Neither scrapes Google Maps, which breaks Google's terms and gets blocked.
Emails come only from the business's own public website or its OSM listing.
"""

from __future__ import annotations

import csv
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

from .audit import USER_AGENT

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join([
    "places.displayName", "places.websiteUri", "places.rating", "places.userRatingCount",
    "places.formattedAddress", "places.nationalPhoneNumber", "places.primaryTypeDisplayName",
    "places.googleMapsUri", "nextPageToken",
])
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Public Overpass servers, tried in order. Each has its own load and rate limits.
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
# OSM servers ask for an honest app name with a contact URL, not a browser-like string.
OSM_HEADERS = {
    "User-Agent": "Hala/0.1 (website lead finder; https://github.com/johnasblasco/hala)",
    "Accept": "application/json, */*",
}

# Plain-language business type -> OpenStreetMap tags.
OSM_TAGS = {
    "dentist": [("amenity", "dentist"), ("healthcare", "dentist")],
    "dental": [("amenity", "dentist"), ("healthcare", "dentist")],
    "clinic": [("amenity", "clinic"), ("amenity", "doctors")],
    "doctor": [("amenity", "doctors"), ("amenity", "clinic")],
    "veterinary": [("amenity", "veterinary")],
    "vet": [("amenity", "veterinary")],
    "pharmacy": [("amenity", "pharmacy")],
    "restaurant": [("amenity", "restaurant")],
    "cafe": [("amenity", "cafe")],
    "coffee": [("amenity", "cafe")],
    "bakery": [("shop", "bakery")],
    "salon": [("shop", "hairdresser"), ("shop", "beauty")],
    "barber": [("shop", "hairdresser")],
    "spa": [("shop", "massage"), ("leisure", "spa"), ("amenity", "spa")],
    "gym": [("leisure", "fitness_centre")],
    "hotel": [("tourism", "hotel"), ("tourism", "guest_house")],
    "resort": [("tourism", "hotel"), ("leisure", "resort")],
    "lawyer": [("office", "lawyer")],
    "law": [("office", "lawyer")],
    "accountant": [("office", "accountant")],
    "real estate": [("office", "estate_agent")],
    "insurance": [("office", "insurance")],
    "plumber": [("craft", "plumber")],
    "electrician": [("craft", "electrician")],
    "contractor": [("craft", "builder"), ("office", "construction_company")],
    "auto repair": [("shop", "car_repair")],
    "car repair": [("shop", "car_repair")],
    "school": [("amenity", "school"), ("amenity", "language_school")],
    "furniture": [("shop", "furniture")],
    "optical": [("shop", "optician")],
    "optician": [("shop", "optician")],
}

CONTACT_PATHS = ("", "/contact", "/contact-us", "/contactus", "/about", "/about-us")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
JUNK_EMAIL = re.compile(
    r"(example\.|sentry|wixpress|domain\.com|yourdomain|email\.com|godaddy|"
    r"\.(png|jpe?g|gif|webp|svg)$|^u00)", re.I)

LEAD_FIELDS = ["name", "email", "website", "category", "city", "reviews", "rating",
               "runs_ads", "phone", "address", "maps_url"]


def search_places(query: str, api_key: str, max_results: int = 60, _post=None) -> list[dict]:
    """Text-search Google Places. Returns up to max_results raw place dicts (API max is 60)."""
    post = _post or _post_json
    places: list[dict] = []
    token = None
    while len(places) < max_results:
        body = {"textQuery": query, "pageSize": min(20, max_results - len(places))}
        if token:
            body["pageToken"] = token
        data = post(PLACES_URL, body, {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELD_MASK})
        places.extend(data.get("places", []))
        token = data.get("nextPageToken")
        if not token:
            break
    return places[:max_results]


def _post_json(url: str, body: dict, headers: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"Google Places API error {e.code}: {detail}") from e


def _get(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            if "html" not in (resp.headers.get("Content-Type") or "html"):
                return None
            return resp.read(1_500_000).decode(resp.headers.get_content_charset() or "utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def extract_emails(html: str, site_domain: str = "") -> list[str]:
    found: list[str] = []
    for m in EMAIL_RE.findall(html):
        email = m.strip(".").lower()
        if JUNK_EMAIL.search(email) or email in found:
            continue
        found.append(email)
    # Prefer an address on the business's own domain, then common inbox names.
    root = site_domain.lower().removeprefix("www.")

    def rank(e: str) -> tuple:
        local, _, dom = e.partition("@")
        return (not (root and dom.endswith(root)),
                local not in {"info", "hello", "contact", "inquiry", "inquiries", "admin", "office"})
    return sorted(found, key=rank)


def find_email(website: str, _get_page=None) -> str:
    get_page = _get_page or _get
    if "://" not in website:
        website = "http://" + website
    domain = urlparse(website).netloc
    for path in CONTACT_PATHS:
        html = get_page(urljoin(website, path) if path else website)
        if html:
            emails = extract_emails(html, domain)
            if emails:
                return emails[0]
    return ""


def _city_from_address(address: str) -> str:
    parts = [p.strip() for p in (address or "").split(",")]
    # "123 Street, Barangay, Makati, Metro Manila, Philippines" -> "Makati"
    return parts[-3] if len(parts) >= 3 else (parts[0] if parts else "")


def place_to_lead(place: dict) -> dict:
    return {
        "name": (place.get("displayName") or {}).get("text", ""),
        "email": "",
        "website": place.get("websiteUri", ""),
        "category": (place.get("primaryTypeDisplayName") or {}).get("text", ""),
        "city": _city_from_address(place.get("formattedAddress", "")),
        "reviews": place.get("userRatingCount", ""),
        "rating": place.get("rating", ""),
        "runs_ads": "",
        "phone": place.get("nationalPhoneNumber", ""),
        "address": place.get("formattedAddress", ""),
        "maps_url": place.get("googleMapsUri", ""),
    }


def google_search(api_key: str):
    def search(query: str, max_results: int) -> list[dict]:
        return [place_to_lead(p) for p in search_places(query, api_key, max_results)]
    return search


# --- OpenStreetMap -----------------------------------------------------------

def split_query(query: str) -> tuple[str, str]:
    """'dentist in Quezon City' -> ('dentist', 'Quezon City')."""
    m = re.match(r"\s*(.+?)\s+(?:in|near|sa)\s+(.+)", query, re.I)
    if not m:
        raise ValueError(f'write searches like "dentist in Quezon City" (got {query!r})')
    return m.group(1).strip(), m.group(2).strip()


def osm_tag_filters(kind: str) -> list[str]:
    k = kind.lower().strip()
    k_single = k[:-1] if k.endswith("s") else k
    for key in (k, k_single):
        if key in OSM_TAGS:
            return [f'["{t}"="{v}"]' for t, v in OSM_TAGS[key]]
    # Unknown type: match the word in business names.
    word = re.sub(r'["\\]', "", k_single)
    return [f'["name"~"{word}",i]["shop"]', f'["name"~"{word}",i]["office"]',
            f'["name"~"{word}",i]["amenity"]', f'["name"~"{word}",i]["craft"]']


def _get_json(url: str, params: dict) -> object:
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", headers=OSM_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _overpass(query: str, _open=None) -> dict:
    """Run an Overpass query, falling back across public servers."""
    open_url = _open or urllib.request.urlopen
    body = urllib.parse.urlencode({"data": query}).encode()
    errors = []
    for url in OVERPASS_URLS:
        req = urllib.request.Request(url, data=body, headers={
            **OSM_HEADERS, "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with open_url(req, timeout=90) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            errors.append(f"{urlparse(url).netloc}: HTTP {e.code}")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            errors.append(f"{urlparse(url).netloc}: {e}")
    raise RuntimeError("all OpenStreetMap servers failed (" + "; ".join(errors) +
                       "). Try again in a few minutes, or use --source google")


def geocode_bbox(place: str, _get=None) -> tuple[float, float, float, float]:
    """Return (south, west, north, east) for a place name via Nominatim."""
    get = _get or _get_json
    try:
        results = get(NOMINATIM_URL, {"q": place, "format": "json", "limit": 1})
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"couldn't look up {place!r}: {e}") from e
    if not results:
        raise RuntimeError(f"OpenStreetMap doesn't know the place {place!r}")
    s, n, w, e = (float(x) for x in results[0]["boundingbox"])
    return s, w, n, e


def element_to_lead(el: dict, city: str) -> dict:
    t = el.get("tags", {})
    website = t.get("website") or t.get("contact:website") or t.get("url") or ""
    if website and "://" not in website:
        website = "http://" + website
    lat = el.get("lat") or (el.get("center") or {}).get("lat")
    lon = el.get("lon") or (el.get("center") or {}).get("lon")
    addr = ", ".join(x for x in (
        " ".join(x for x in (t.get("addr:housenumber", ""), t.get("addr:street", "")) if x),
        t.get("addr:city", "")) if x)
    kind = next((t[k] for k in ("amenity", "healthcare", "shop", "office", "craft", "tourism", "leisure")
                 if k in t), "")
    return {
        "name": t.get("name", ""),
        "email": (t.get("email") or t.get("contact:email") or "").split(";")[0].strip(),
        "website": website,
        "category": kind.replace("_", " "),
        "city": t.get("addr:city") or city,
        "reviews": "", "rating": "", "runs_ads": "",
        "phone": t.get("phone") or t.get("contact:phone") or "",
        "address": addr,
        "maps_url": f"https://www.openstreetmap.org/{el.get('type')}/{el.get('id')}"
                    if el.get("id") else (f"https://maps.google.com/?q={lat},{lon}" if lat else ""),
    }


def osm_search(_overpass_fn=None, _geocode=None):
    run_query = _overpass_fn or _overpass
    geocode = _geocode or geocode_bbox

    def search(query: str, max_results: int) -> list[dict]:
        kind, place = split_query(query)
        s, w, n, e = geocode(place)
        bbox = f"({s},{w},{n},{e})"
        parts = "".join(f"nwr{f}{bbox};" for f in osm_tag_filters(kind))
        data = run_query(f"[out:json][timeout:60];({parts});out center tags {max_results};")
        time.sleep(1)  # be polite to the free public servers
        return [element_to_lead(el, place) for el in data.get("elements", [])
                if el.get("tags", {}).get("name")]
    return search


# --- Shared ----------------------------------------------------------------

def find_leads(queries: list[str], search, max_per_query: int = 60, workers: int = 8,
               _find_email=None) -> tuple[list[dict], list[dict]]:
    """Return (leads with a website, businesses with no website at all).

    `search(query, max_results)` returns lead dicts (see google_search / osm_search).
    """
    email_of = _find_email or find_email
    seen: set[str] = set()
    with_site, no_site = [], []
    for q in queries:
        for lead in search(q, max_per_query):
            key = (lead["name"] + lead["address"]).lower()
            if key in seen:
                continue
            seen.add(key)
            (with_site if lead["website"] else no_site).append(lead)
    need_email = [l for l in with_site if not l["email"]]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for lead, email in zip(need_email, pool.map(lambda l: email_of(l["website"]), need_email)):
            lead["email"] = email
    return with_site, no_site


def write_leads(path: str, leads: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=LEAD_FIELDS)
        w.writeheader()
        w.writerows(leads)


def api_key_from_env() -> str:
    return os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("GOOGLE_PLACES_API_KEY") or ""
