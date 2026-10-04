"""Lead finder: Google Places search plus an email lookup on each business's own website.

Uses the official Places API (New) rather than scraping Google Maps, which
breaks Google's terms and gets blocked. Emails come only from the business's
own public website (homepage, then common contact pages).
"""

from __future__ import annotations

import csv
import json
import os
import re
import urllib.error
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


def find_leads(queries: list[str], api_key: str, max_per_query: int = 60, workers: int = 8,
               _search=None, _find_email=None) -> tuple[list[dict], list[dict]]:
    """Return (leads with a website, businesses with no website at all)."""
    search = _search or search_places
    email_of = _find_email or find_email
    seen: set[str] = set()
    with_site, no_site = [], []
    for q in queries:
        for place in search(q, api_key, max_per_query):
            lead = place_to_lead(place)
            key = (lead["name"] + lead["address"]).lower()
            if key in seen:
                continue
            seen.add(key)
            (with_site if lead["website"] else no_site).append(lead)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for lead, email in zip(with_site, pool.map(lambda l: email_of(l["website"]), with_site)):
            lead["email"] = email
    return with_site, no_site


def write_leads(path: str, leads: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=LEAD_FIELDS)
        w.writeheader()
        w.writerows(leads)


def api_key_from_env() -> str:
    return os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("GOOGLE_PLACES_API_KEY") or ""
