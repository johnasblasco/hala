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
)
RETRY_STATUSES = (429, 503, 504)  # busy / rate-limited: wait and retry the same server
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


def search_places(query: str, api_key: str, max_results: int = 60, _post=None,
                  country: str = "") -> list[dict]:
    """Text-search Google Places. Returns up to max_results raw place dicts (API max is 60)."""
    post = _post or _post_json
    places: list[dict] = []
    token = None
    while len(places) < max_results:
        body = {"textQuery": query, "pageSize": min(20, max_results - len(places))}
        if re.fullmatch(r"[A-Za-z]{2}", country or ""):
            body["regionCode"] = country.upper()  # bias results to that country
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


def google_search(api_key: str, country: str = ""):
    def search(query: str, max_results: int) -> list[dict]:
        return [place_to_lead(p) for p in search_places(query, api_key, max_results, country=country)]
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


class SearchTimeout(RuntimeError):
    """The search ran out of its time budget (servers too slow or busy)."""


def _overpass(query: str, _open=None, _sleep=time.sleep, notify=None, deadline: float | None = None,
              _clock=time.monotonic) -> dict:
    """Run an Overpass query. Waits and retries when a server is busy, then tries the next one.

    `deadline` (a _clock() value) caps the total time, so a hosted request (Vercel stops
    functions after a few minutes) ends with a clear error instead of being cut off.
    """
    open_url = _open or urllib.request.urlopen
    body = urllib.parse.urlencode({"data": query}).encode()
    errors = []

    def remaining() -> float:
        return float("inf") if deadline is None else deadline - _clock()

    for url in OVERPASS_URLS:
        host = urlparse(url).netloc
        for attempt in range(3):
            if remaining() < 10:
                raise SearchTimeout(
                    "OpenStreetMap's free servers are too slow right now, so the search was "
                    "stopped. Wait a few minutes and try again with fewer towns, or add a "
                    "Google API key. (Details: " + ("; ".join(errors) or "no answer in time") + ")")
            req = urllib.request.Request(url, data=body, headers={
                **OSM_HEADERS, "Content-Type": "application/x-www-form-urlencoded"})
            try:
                with open_url(req, timeout=min(150, max(5, remaining() - 5))) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                if e.code in RETRY_STATUSES and attempt < 2:
                    try:
                        wait = int(e.headers.get("Retry-After", "")) if e.headers else 0
                    except ValueError:
                        wait = 0
                    wait = min(max(wait, 15 * (attempt + 1)), 60)
                    if remaining() - wait < 20:
                        errors.append(f"{host}: HTTP {e.code} (busy)")
                        break  # not enough time to wait; try the next server
                    if notify:
                        notify(f"OpenStreetMap is busy, retrying in {wait}s")
                    _sleep(wait)
                    continue
                errors.append(f"{host}: HTTP {e.code}")
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                errors.append(f"{host}: {e}")
            break
    raise RuntimeError("OpenStreetMap's free servers are busy right now. Wait a few minutes and "
                       "try again, or add a Google API key. (Details: " + "; ".join(errors) + ")")


def geocode_bbox(place: str, _get=None, country: str = "") -> tuple[float, float, float, float]:
    """Return (south, west, north, east) for a place name via Nominatim.
    `country` (ISO code like 'PH', 'US') keeps same-named towns elsewhere out."""
    get = _get or _get_json
    params = {"q": place, "format": "json", "limit": 1}
    if re.fullmatch(r"[A-Za-z]{2}", country or ""):
        params["countrycodes"] = country.lower()
    try:
        results = get(NOMINATIM_URL, params)
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


def osm_search(_overpass_fn=None, _geocode=None, notify=None, _sleep=time.sleep, country: str = "",
               budget_seconds: float | None = None, _clock=time.monotonic):
    """Return an OSM search function. Its `.batch` runs many places as ONE Overpass query,
    which avoids the public servers' rate limits. `budget_seconds` caps the whole search."""
    geocode = _geocode or (lambda place: geocode_bbox(place, country=country))

    def batch(queries: list[str], max_per_query: int) -> list[dict]:
        deadline = _clock() + budget_seconds if budget_seconds else None

        def run_query(q: str) -> dict:
            if _overpass_fn:
                return _overpass_fn(q)
            return _overpass(q, notify=notify, deadline=deadline, _sleep=_sleep, _clock=_clock)

        places = []  # (place name, bbox)
        parts = []
        for i, query in enumerate(queries):
            kind, place = split_query(query)
            if deadline is not None and deadline - _clock() < 60:
                raise SearchTimeout(f"Looking up {len(queries)} towns took too long. "
                                    "Try fewer towns at a time.")
            if notify:
                notify(f"Looking up {place}")
            if i:
                _sleep(1)  # Nominatim allows one request per second
            bbox = geocode(place)
            places.append((place, bbox))
            box = "({},{},{},{})".format(*bbox)
            parts.extend(f"nwr{f}{box};" for f in osm_tag_filters(kind))
        if notify:
            notify("Searching OpenStreetMap")
        limit = max_per_query * len(queries)
        data = run_query(f"[out:json][timeout:120];({''.join(parts)});out center tags {limit};")
        leads = []
        for el in data.get("elements", []):
            if not el.get("tags", {}).get("name"):
                continue
            # "Malolos City, Bulacan, Philippines" -> "Malolos City"
            leads.append(element_to_lead(el, _place_for(el, places).split(",")[0].strip()))
        return leads

    def search(query: str, max_results: int) -> list[dict]:
        return batch([query], max_results)

    search.batch = batch
    return search


def _place_for(el: dict, places: list) -> str:
    lat = el.get("lat") or (el.get("center") or {}).get("lat")
    lon = el.get("lon") or (el.get("center") or {}).get("lon")
    if lat is not None and lon is not None:
        for name, (s, w, n, e) in places:
            if s <= lat <= n and w <= lon <= e:
                return name
    return places[0][0] if places else ""


# --- Shared ----------------------------------------------------------------

def find_leads(queries: list[str], search, max_per_query: int = 60, workers: int = 8,
               _find_email=None, lookup_emails: bool = True) -> tuple[list[dict], list[dict]]:
    """Return (leads with a website, businesses with no website at all).

    `search(query, max_results)` returns lead dicts (see google_search / osm_search).
    """
    email_of = _find_email or find_email
    seen: set[str] = set()
    with_site, no_site = [], []
    if hasattr(search, "batch"):
        found = search.batch(queries, max_per_query)
    else:
        found = [lead for q in queries for lead in search(q, max_per_query)]
    for lead in found:
        key = (lead["name"] + lead["address"]).lower()
        if key in seen:
            continue
        seen.add(key)
        (with_site if lead["website"] else no_site).append(lead)
    if not lookup_emails:
        return with_site, no_site
    need_email = [l for l in with_site if not l["email"]]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for lead, email in zip(need_email, pool.map(lambda l: email_of(l["website"]), need_email)):
            lead["email"] = email
    return with_site, no_site


NO_SITE_FIELDS = ["name", "phone", "city", "category", "address", "maps_url",
                  "facebook_search", "message"]


def facebook_search_url(lead: dict) -> str:
    q = " ".join(x for x in (lead.get("name"), lead.get("city")) if x)
    return "https://www.facebook.com/search/pages/?" + urllib.parse.urlencode({"q": q})


def write_leads(path: str, leads: list[dict], fields: list[str] = LEAD_FIELDS) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(leads)


def api_key_from_env() -> str:
    return os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("GOOGLE_PLACES_API_KEY") or ""
