"""Website auditor: fetches a page and reports problems in business terms.

Every finding answers "what does this cost the owner?", not just "what is
technically wrong?". Findings are ranked by impact so the pitch can lead with
the single most expensive problem.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from urllib.parse import urlparse

USER_AGENT = "Mozilla/5.0 (compatible; HalaAudit/0.1)"
FETCH_TIMEOUT = 15

# Points deducted from 100 per finding, by impact level.
PENALTY = {3: 15, 2: 8, 1: 4}

PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
YEAR_RE = re.compile(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(\d{4})", re.I)
ANALYTICS_MARKERS = (
    "googletagmanager.com", "google-analytics.com", "gtag(", "plausible.io",
    "fathom", "clarity.ms", "connect.facebook.net", "umami",
)


@dataclass
class Finding:
    id: str
    impact: int  # 3 = costs customers now, 2 = hurts trust/ranking, 1 = polish
    title: str   # plain-language, owner-facing
    detail: str
    fix: str


@dataclass
class AuditResult:
    url: str
    final_url: str | None = None
    status: int | None = None
    load_seconds: float | None = None
    html_bytes: int = 0
    reachable: bool = True
    error: str | None = None
    page_title: str | None = None
    findings: list[Finding] = field(default_factory=list)

    @property
    def score(self) -> int:
        if not self.reachable:
            return 0
        return max(0, 100 - sum(PENALTY[f.impact] for f in self.findings))

    @property
    def top_finding(self) -> Finding | None:
        return self.findings[0] if self.findings else None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["score"] = self.score
        return d


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.in_title = False
        self.in_script_ld = False
        self.in_ignored = 0
        self.meta: dict[str, str] = {}
        self.h1_count = 0
        self.img_total = 0
        self.img_no_alt = 0
        self.links: list[str] = []
        self.form_count = 0
        self.has_favicon = False
        self.html_lang = None
        self.ld_json: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.html_lang = a.get("lang") or None
        elif tag == "title":
            self.in_title = True
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key:
                self.meta[key] = a.get("content", "")
        elif tag == "h1":
            self.h1_count += 1
        elif tag == "img":
            self.img_total += 1
            if not a.get("alt", "").strip():
                self.img_no_alt += 1
        elif tag == "a":
            self.links.append(a.get("href", ""))
        elif tag == "form":
            self.form_count += 1
        elif tag == "link":
            if "icon" in a.get("rel", "").lower():
                self.has_favicon = True
        elif tag == "script":
            if a.get("type", "").lower() == "application/ld+json":
                self.in_script_ld = True
            else:
                self.in_ignored += 1
        elif tag == "style":
            self.in_ignored += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag == "script":
            if self.in_script_ld:
                self.in_script_ld = False
            elif self.in_ignored:
                self.in_ignored -= 1
        elif tag == "style" and self.in_ignored:
            self.in_ignored -= 1

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif self.in_script_ld:
            self.ld_json.append(data)
        elif not self.in_ignored:
            self.text_parts.append(data)


def _schema_types(blobs: list[str]) -> set[str]:
    types: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            t = node.get("@type")
            if isinstance(t, str):
                types.add(t)
            elif isinstance(t, list):
                types.update(x for x in t if isinstance(x, str))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for blob in blobs:
        try:
            walk(json.loads(blob))
        except ValueError:
            continue
    return types


LOCAL_SCHEMA_HINTS = ("LocalBusiness", "Dentist", "Restaurant", "Store", "Attorney",
                      "MedicalBusiness", "HomeAndConstructionBusiness", "AutoRepair",
                      "Plumber", "Electrician", "RealEstateAgent", "Organization")


def analyze_html(
    html: str,
    url: str,
    *,
    final_url: str | None = None,
    load_seconds: float | None = None,
    status: int | None = 200,
    today: _dt.date | None = None,
) -> AuditResult:
    """Run every check against already-fetched HTML. Pure, so it is testable offline."""
    today = today or _dt.date.today()
    p = _PageParser()
    p.feed(html)
    text = " ".join(" ".join(p.text_parts).split())
    lower_html = html.lower()
    final = final_url or url

    r = AuditResult(url=url, final_url=final, status=status, load_seconds=load_seconds,
                    html_bytes=len(html.encode("utf-8", "ignore")),
                    page_title=p.title.strip() or None)
    add = r.findings.append

    if urlparse(final).scheme != "https":
        add(Finding("no_https", 3, "Browsers label your site \"Not secure\"",
                    "The site loads without HTTPS. Chrome and Safari show a warning "
                    "next to the address, and many visitors leave right there.",
                    "Serve the site over HTTPS (free with Cloudflare)."))

    viewport = p.meta.get("viewport", "")
    if "width=device-width" not in viewport.replace(" ", ""):
        add(Finding("not_mobile", 3, "The site isn't built for phones",
                    "There's no mobile viewport, so phones show a shrunken desktop page. "
                    "Most local searches happen on a phone.",
                    "Rebuild with a responsive layout."))

    tel_links = [l for l in p.links if l.lower().startswith("tel:")]
    mail_links = [l for l in p.links if l.lower().startswith("mailto:")]
    phone_in_text = bool(PHONE_RE.search(text))
    if not tel_links and phone_in_text:
        add(Finding("no_click_to_call", 3, "Phone visitors can't tap to call you",
                    "Your number is on the page but it isn't a tap-to-call link, so mobile "
                    "visitors have to copy it by hand. Many just call the next business.",
                    "Wrap the number in a tel: link and add a sticky call button on mobile."))
    if not tel_links and not mail_links and p.form_count == 0 and not phone_in_text:
        add(Finding("no_contact", 3, "There's no obvious way to contact you",
                    "We couldn't find a phone number, email link or contact form on the homepage.",
                    "Put the phone number, a short form and a booking button above the fold."))

    if load_seconds is not None and load_seconds > 2.5:
        add(Finding("slow", 2, f"The page took {load_seconds:.1f}s to respond",
                    "Visitors start leaving after about 3 seconds, and slow pages also rank lower.",
                    "Use a static site on a CDN with compressed images."))
    if r.html_bytes > 600_000:
        add(Finding("heavy", 2, "The page is unusually heavy",
                    f"The HTML alone is {r.html_bytes // 1024} KB, which slows the page "
                    "down on mobile data.",
                    "Strip page-builder bloat and lazy-load images."))

    title = (p.title or "").strip()
    if not title or len(title) < 15 or title.lower() in {"home", "homepage", "welcome", "index"}:
        add(Finding("weak_title", 2, "Google doesn't know what you do or where",
                    f"The page title is {title!r}. That's the headline people see in "
                    "Google, so it should name your service and your city.",
                    "Use a title like \"Emergency Plumber in Quezon City | Name\"."))

    m = YEAR_RE.search(text)
    if m and int(m.group(1)) < today.year - 1:
        add(Finding("stale", 2, "The site looks abandoned",
                    f"The footer says © {m.group(1)}. Visitors take that to mean "
                    "the business might be closed.",
                    "Keep the site current; a care plan handles this."))

    if not p.meta.get("description", "").strip():
        add(Finding("no_description", 1, "Google writes your search snippet for you",
                    "There's no meta description, so Google picks random text from the page "
                    "to show under your listing.",
                    "Write a 150-character description with a clear call to action."))

    if p.h1_count == 0:
        add(Finding("no_h1", 1, "There's no clear main headline",
                    "The page has no H1 heading. Visitors and search engines can't tell "
                    "at a glance what the page is about.",
                    "Add a single headline that says what you do and where."))

    if p.img_total >= 3 and p.img_no_alt / p.img_total > 0.3:
        add(Finding("img_alt", 1, "Images are invisible to Google and screen readers",
                    f"{p.img_no_alt} of {p.img_total} images have no alt text.",
                    "Describe each image in a few words."))

    if not any(h in t for t in _schema_types(p.ld_json) for h in LOCAL_SCHEMA_HINTS):
        add(Finding("no_schema", 1, "You're missing from Google's rich local results",
                    "There's no LocalBusiness structured data, so Google can't confidently "
                    "show your hours, rating and location.",
                    "Add LocalBusiness JSON-LD with your address, hours and phone."))

    if not any(mark in lower_html for mark in ANALYTICS_MARKERS):
        add(Finding("no_analytics", 1, "You can't see how many people visit",
                    "We found no analytics, so there's no way to know whether the site "
                    "brings in customers.",
                    "Add privacy-friendly analytics and a monthly report."))

    if "og:image" not in p.meta:
        add(Finding("no_og", 1, "Shared links to your site look blank",
                    "There's no preview image, so links posted on Facebook or Messenger "
                    "show up without a picture.",
                    "Add og:title, og:description and og:image tags."))

    if not p.has_favicon:
        add(Finding("no_favicon", 1, "There's no icon in the browser tab",
                    "A missing favicon makes the site look unfinished.",
                    "Add your logo as a favicon."))

    r.findings.sort(key=lambda f: -f.impact)
    return r


def fetch(url: str, timeout: float = FETCH_TIMEOUT) -> tuple[str, str, int, float]:
    if "://" not in url:
        url = "http://" + url
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(3_000_000)
        elapsed = time.monotonic() - start
        charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, "replace"), resp.geturl(), resp.status, elapsed


def audit(url: str) -> AuditResult:
    """Fetch a URL and audit it. A site that won't load is itself the top finding."""
    try:
        html, final_url, status, elapsed = fetch(url)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        r = AuditResult(url=url, reachable=False, error=str(e))
        r.findings.append(Finding(
            "unreachable", 3, "The website doesn't load",
            f"We couldn't open {url} ({e}). Anyone who finds you on Google or "
            "Facebook and clicks through sees an error.",
            "Get a fast, reliable site back online."))
        return r
    return analyze_html(html, url, final_url=final_url, load_seconds=elapsed, status=status)
