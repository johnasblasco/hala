"""Website previews: a one-page site for a lead, to send as "here's what yours could look like".

Claude (when available) writes only the words, as structured data. The page
itself always comes from the template below, so every preview looks
professional, and model output can't inject markup: all text is escaped and
only http(s) links are used.
"""

from __future__ import annotations

import json
import re
from html import escape
from urllib.parse import quote_plus, urlparse

from .pitch import MODEL

LANGUAGES = ("English", "Filipino", "Taglish")

# Business type -> (accent, accent-dark, soft background)
THEMES = {
    "dentist": ("#0e9f9a", "#0a6e6b", "#e7f7f6"),
    "dental": ("#0e9f9a", "#0a6e6b", "#e7f7f6"),
    "clinic": ("#2563eb", "#1e40af", "#eaf1ff"),
    "doctor": ("#2563eb", "#1e40af", "#eaf1ff"),
    "salon": ("#c2416b", "#8f2b4d", "#fcedf2"),
    "hairdresser": ("#c2416b", "#8f2b4d", "#fcedf2"),
    "beauty": ("#c2416b", "#8f2b4d", "#fcedf2"),
    "spa": ("#4d7c5a", "#355a40", "#edf5ef"),
    "massage": ("#4d7c5a", "#355a40", "#edf5ef"),
    "resort": ("#0b7fae", "#075b7d", "#e6f4fa"),
    "hotel": ("#0b7fae", "#075b7d", "#e6f4fa"),
    "restaurant": ("#c2561d", "#8d3d12", "#fdf0e8"),
    "cafe": ("#8a5a3b", "#5f3d27", "#f6efe9"),
    "gym": ("#d33a2c", "#99261c", "#fdeceb"),
    "fitness": ("#d33a2c", "#99261c", "#fdeceb"),
    "veterinary": ("#3f8f3f", "#2b662b", "#ecf6ec"),
    "vet": ("#3f8f3f", "#2b662b", "#ecf6ec"),
    "lawyer": ("#1f3a68", "#13264a", "#ebeff7"),
    "law": ("#1f3a68", "#13264a", "#ebeff7"),
    "accountant": ("#1f3a68", "#13264a", "#ebeff7"),
    "real estate": ("#475569", "#334155", "#eef1f5"),
    "estate agent": ("#475569", "#334155", "#eef1f5"),
    "auto repair": ("#b91c1c", "#7f1d1d", "#fbeaea"),
    "car repair": ("#b91c1c", "#7f1d1d", "#fbeaea"),
    "school": ("#6d28d9", "#4c1d95", "#f1ebfd"),
}
DEFAULT_THEME = ("#2457d6", "#183c99", "#eaf0fd")

# Business type -> (customer word, default services). Used when there's no AI
# and as a hint for Claude. Deliberately generic: no prices, names or claims.
DEFAULTS = {
    "dentist": ("patients", ["Check-ups & cleaning", "Fillings & extractions", "Braces & aligners",
                             "Teeth whitening", "Dentures & crowns", "Kids' dentistry"]),
    "clinic": ("patients", ["General consultations", "Check-ups & lab requests", "Vaccinations",
                            "Medical certificates", "Follow-up care", "Referrals to specialists"]),
    "salon": ("clients", ["Haircuts & styling", "Hair color & treatments", "Rebond & keratin",
                          "Manicure & pedicure", "Make-up", "Event styling"]),
    "spa": ("guests", ["Full body massage", "Foot spa & reflexology", "Facials", "Body scrubs",
                       "Couples packages", "Home service"]),
    "resort": ("guests", ["Day tour", "Overnight rooms", "Swimming pools", "Events & reunions",
                          "Function hall", "Food & catering"]),
    "restaurant": ("customers", ["Dine-in", "Take-out", "Delivery", "Group orders & catering",
                                 "Private events", "Daily specials"]),
    "cafe": ("customers", ["Coffee & drinks", "Pastries & snacks", "All-day meals", "Study-friendly space",
                           "Take-out", "Small events"]),
    "gym": ("members", ["Monthly membership", "Personal training", "Group classes", "Weight loss programs",
                        "Strength training", "Day passes"]),
    "vet": ("pet owners", ["Check-ups & consultations", "Vaccinations", "Deworming", "Grooming",
                           "Surgery", "Pet supplies"]),
    "lawyer": ("clients", ["Legal consultations", "Contracts & notarization", "Family law",
                           "Business & corporate", "Property & land titles", "Litigation"]),
    "accountant": ("clients", ["Bookkeeping", "Tax filing", "Business registration", "Payroll",
                               "Financial statements", "Audit support"]),
    "real estate": ("clients", ["House & lot for sale", "Condo units", "Lot only", "Rentals",
                                "Home loan assistance", "Property tripping"]),
    "auto repair": ("customers", ["Change oil & tune-up", "Brake & suspension", "Engine repair",
                                  "Aircon service", "Electrical & diagnostics", "Body & paint"]),
    "school": ("parents", ["Preschool", "Elementary", "Tutoring", "Enrichment classes",
                           "School tours", "Enrollment assistance"]),
}
ALIASES = {"dental": "dentist", "doctor": "clinic", "hairdresser": "salon", "beauty": "salon",
           "massage": "spa", "hotel": "resort", "guest house": "resort", "fitness": "gym",
           "fitness centre": "gym", "veterinary": "vet", "law": "lawyer", "estate agent": "real estate",
           "car repair": "auto repair"}


def business_type(lead: dict) -> str:
    cat = (lead.get("category") or "").lower()
    for key in list(DEFAULTS) + list(ALIASES):
        if key in cat:
            return ALIASES.get(key, key)
    return ""


def theme_for(lead: dict) -> tuple[str, str, str]:
    cat = (lead.get("category") or "").lower()
    return next((t for k, t in THEMES.items() if k in cat), DEFAULT_THEME)


def safe_url(url: str) -> str:
    """Only plain http(s) links make it into the page."""
    url = (url or "").strip()
    try:
        parts = urlparse(url)
    except ValueError:
        return ""
    if parts.scheme in ("http", "https") and parts.netloc and not re.search(r"[\s\"'<>]", url):
        return url
    return ""


# --- content -----------------------------------------------------------------

CONTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "subheadline": {"type": "string"},
        "services": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "description": {"type": "string"}},
            "required": ["name", "description"], "additionalProperties": False}},
        "why_us": {"type": "array", "items": {"type": "string"}},
        "about": {"type": "string"},
        "faq": {"type": "array", "items": {
            "type": "object",
            "properties": {"q": {"type": "string"}, "a": {"type": "string"}},
            "required": ["q", "a"], "additionalProperties": False}},
        "cta": {"type": "string"},
    },
    "required": ["headline", "subheadline", "services", "why_us", "about", "faq", "cta"],
    "additionalProperties": False,
}

SYSTEM = """You write the text for a one-page website preview for a small local business in the Philippines. A web designer will show it to the owner as "here's what your site could look like".

Rules:
- Use ONLY facts given to you. Never invent prices, years in business, awards, certifications, staff or doctor names, testimonials, statistics or promotions. If you don't know something, write around it.
- If the owner's notes list services, hours or specialties, use them. Otherwise use typical services for this kind of business, phrased generally.
- headline: under 9 words, benefit-led, can mention the town. subheadline: one sentence.
- 4 to 6 services, each with a one-sentence description. 3 short "why choose us" points that don't make unverifiable claims (e.g. "Easy to reach in <town>", "Book by call or message").
- about: 2 to 3 warm sentences. faq: 3 practical questions (booking, location, payment or what to bring) with answers that don't invent facts; when unsure, say to call or message.
- cta: a short button label like "Book an appointment".
- Write in the language given in `language` (Taglish = natural Filipino-English mix)."""


def default_content(lead: dict, notes: str = "") -> dict:
    kind = business_type(lead)
    who, services = DEFAULTS.get(kind, ("customers", ["Our services", "Consultations",
                                                      "Inquiries & bookings"]))
    noted = [s.strip(" -•\t") for s in re.split(r"[\n,;]", notes or "") if s.strip(" -•\t")]
    if 2 <= len(noted) <= 8 and all(len(s) < 60 for s in noted):
        services = noted
    city = lead.get("city") or ""
    label = kind or (lead.get("category") or "business")
    return {
        "headline": f"Your trusted {label} in {city}" if city else f"Your trusted local {label}",
        "subheadline": f"Friendly, reliable service for {who} in {city or 'our community'}. "
                       "Call or message us to book.",
        "services": [{"name": s, "description": "Ask us about availability and schedules."}
                     for s in services[:6]],
        "why_us": [f"Easy to reach{' in ' + city if city else ''}", "Book by call or message",
                   "Friendly, welcoming team"],
        "about": f"{lead.get('name', 'We')} serves {who} in {city or 'the area'}. "
                 "Reach out any time and we'll be happy to help.",
        "faq": [
            {"q": "How do I book?", "a": "Call or message us and we'll confirm a schedule that works for you."},
            {"q": "Where are you located?", "a": lead.get("address") or (
                f"We're in {city}. Tap 'Get directions' for the map." if city
                else "Tap 'Get directions' for the map.")},
            {"q": "What are your hours?", "a": "Please call or message us for our current schedule."},
        ],
        "cta": "Book now" if kind in ("dentist", "clinic", "salon", "spa", "vet", "gym") else "Contact us",
    }


def claude_content(lead: dict, notes: str, language: str, client) -> dict | None:
    """Ask Claude for the page text. Returns None if Claude is unavailable or declines."""
    import anthropic

    kind = business_type(lead)
    facts = {
        "business_name": lead.get("name"),
        "type": lead.get("category") or kind,
        "town": lead.get("city"),
        "address": lead.get("address"),
        "google_rating": lead.get("rating") or None,
        "review_count": lead.get("reviews") or None,
        "owner_notes": notes or None,
        "typical_services_hint": DEFAULTS.get(kind, (None, None))[1],
        "language": language if language in LANGUAGES else "English",
    }
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": CONTENT_SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": json.dumps(facts, ensure_ascii=False)}],
        )
    except anthropic.APIError:
        return None
    if response.stop_reason in ("refusal", "max_tokens"):
        return None
    try:
        data = json.loads("".join(b.text for b in response.content if b.type == "text"))
    except ValueError:
        return None
    if not data.get("services"):
        return None
    return data


# --- page ------------------------------------------------------------------

def render_preview(lead: dict, content: dict, sender: dict, photos: list[str] | None = None,
                   facebook_url: str = "") -> str:
    accent, dark, soft = theme_for(lead)
    e = lambda s: escape(str(s or ""))  # noqa: E731
    name = e(lead.get("name") or "Your Business")
    city = lead.get("city") or ""
    phone = (lead.get("phone") or "").strip()
    tel = re.sub(r"[^\d+]", "", phone)
    photos = [p for p in (safe_url(u) for u in (photos or [])) if p][:6]
    fb = safe_url(facebook_url)
    place_q = quote_plus(" ".join(x for x in (lead.get("name"), lead.get("address"), city) if x))
    directions = f"https://www.google.com/maps/search/?api=1&query={place_q}"
    map_embed = f"https://maps.google.com/maps?q={place_q}&output=embed"

    buttons = []
    if tel:
        buttons.append(f'<a class="btn primary" href="tel:{e(tel)}">Call {e(phone)}</a>')
    if fb:
        buttons.append(f'<a class="btn" href="{e(fb)}" target="_blank" rel="noopener">Message us on Facebook</a>')
    buttons.append(f'<a class="btn" href="{e(directions)}" target="_blank" rel="noopener">Get directions</a>')

    services = "".join(
        f'<div class="svc"><h3>{e(s.get("name"))}</h3><p>{e(s.get("description"))}</p></div>'
        for s in content.get("services", [])[:6])
    why = "".join(f"<li>{e(w)}</li>" for w in content.get("why_us", [])[:4])
    faq = "".join(f"<details><summary>{e(f.get('q'))}</summary><p>{e(f.get('a'))}</p></details>"
                  for f in content.get("faq", [])[:5])
    gallery = ("<section class='wrap'><h2>Gallery</h2><div class='gallery'>" + "".join(
        f'<img src="{e(p)}" alt="{name}" loading="lazy">' for p in photos) + "</div></section>"
               ) if len(photos) > 1 else ""
    hero_bg = (f"linear-gradient(rgba(10,15,25,.55),rgba(10,15,25,.65)),url('{e(photos[0])}') center/cover"
               if photos else f"linear-gradient(135deg,{accent},{dark})")
    rating = ""
    if lead.get("rating") and lead.get("reviews"):
        rating = f'<p class="rating">★ {e(lead["rating"])} on Google · {e(lead["reviews"])} reviews</p>'
    by = e(sender.get("name") or "a web designer")
    studio = e(sender.get("company") or "")
    contact_lines = "".join(x for x in (
        f"<p><b>Address</b><br>{e(lead.get('address'))}{', ' + e(city) if city and city not in (lead.get('address') or '') else ''}</p>"
        if lead.get("address") or city else "",
        f'<p><b>Phone</b><br><a href="tel:{e(tel)}">{e(phone)}</a></p>' if tel else "",
        f'<p><b>Facebook</b><br><a href="{e(fb)}" target="_blank" rel="noopener">Message us</a></p>' if fb else "",
    ))

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{name}{' | ' + e(city) if city else ''}</title>
<style>
:root{{--a:{accent};--d:{dark};--s:{soft};--ink:#1c1f24;--mute:#5b6270;--line:#e6e8ec}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}
body{{margin:0;font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--ink);background:#fff}}
a{{color:var(--a)}}h1,h2,h3{{line-height:1.2;margin:0}}
.banner{{background:#111;color:#fff;font-size:13px;text-align:center;padding:8px 16px}}
.banner b{{color:#ffd166}}
nav{{position:sticky;top:0;z-index:5;background:rgba(255,255,255,.95);backdrop-filter:blur(6px);border-bottom:1px solid var(--line)}}
nav .wrap{{display:flex;align-items:center;justify-content:space-between;gap:12px;padding-top:12px;padding-bottom:12px}}
nav .logo{{font-weight:800;font-size:18px;color:var(--d);text-decoration:none}}
nav .links a{{margin-left:18px;color:var(--ink);text-decoration:none;font-size:15px}}
.wrap{{max-width:1080px;margin:0 auto;padding:0 20px}}
.hero{{background:{hero_bg};color:#fff;padding:88px 0 96px}}
.hero h1{{font-size:clamp(32px,5vw,52px);max-width:760px}}
.hero p.sub{{font-size:clamp(17px,2.2vw,20px);max-width:640px;opacity:.95;margin:16px 0 28px}}
.rating{{display:inline-block;background:rgba(255,255,255,.15);padding:4px 12px;border-radius:999px;font-size:14px;margin:0 0 16px}}
.btns{{display:flex;flex-wrap:wrap;gap:12px}}
.btn{{display:inline-block;padding:13px 22px;border-radius:10px;font-weight:700;text-decoration:none;background:var(--s);color:var(--d);border:1px solid rgba(0,0,0,.06)}}
.about .card .btn,.cta-band .btn{{background:#fff}}
.btn.primary{{background:var(--a);color:#fff;box-shadow:0 6px 20px rgba(0,0,0,.18)}}
.hero .btn:not(.primary){{background:rgba(255,255,255,.14);color:#fff;border:1px solid rgba(255,255,255,.45)}}
section{{padding:72px 0}}
section h2{{font-size:clamp(26px,3.5vw,34px);margin-bottom:28px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}}
.svc{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:22px;border-top:4px solid var(--a)}}
.svc h3{{font-size:18px;margin-bottom:6px}}.svc p{{margin:0;color:var(--mute)}}
.alt{{background:var(--s)}}
.why{{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}}
.why li{{background:#fff;border-radius:12px;padding:18px 18px 18px 48px;position:relative;font-weight:600}}
.why li::before{{content:"✓";position:absolute;left:18px;top:16px;color:var(--a);font-weight:900}}
.about{{display:grid;grid-template-columns:1fr 1fr;gap:40px;align-items:center}}
.about p{{font-size:18px;color:#333}}
.about .card{{background:var(--s);border-radius:16px;padding:28px}}
details{{border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:10px;background:#fff}}
summary{{font-weight:700;cursor:pointer}}details p{{margin:10px 0 0;color:var(--mute)}}
.gallery{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}}
.gallery img{{width:100%;height:220px;object-fit:cover;border-radius:12px}}
.contact{{display:grid;grid-template-columns:1fr 1.3fr;gap:28px}}
.contact iframe{{width:100%;height:320px;border:0;border-radius:14px}}
.cta-band{{background:linear-gradient(135deg,var(--a),var(--d));color:#fff;text-align:center;padding:56px 0}}
.cta-band h2{{margin-bottom:18px}}
footer{{padding:28px 0;color:var(--mute);font-size:14px;text-align:center}}
.callbar{{display:none}}
@media(max-width:760px){{
  nav .links{{display:none}}.about,.contact{{grid-template-columns:1fr}}
  .hero{{padding:56px 0 64px}}section{{padding:52px 0}}
  .callbar{{display:flex;position:fixed;bottom:0;left:0;right:0;z-index:9;gap:8px;padding:10px 12px;background:#fff;border-top:1px solid var(--line)}}
  .callbar a{{flex:1;text-align:center}}body{{padding-bottom:72px}}
}}
</style></head>
<body>
<div class="banner"><b>Design preview</b> for {name}, prepared by {by}{' · ' + studio if studio else ''}. Not a live website.</div>
<nav><div class="wrap"><a class="logo" href="#top">{name}</a>
<div class="links"><a href="#services">Services</a><a href="#about">About</a><a href="#faq">FAQ</a><a href="#contact">Contact</a></div></div></nav>
<header class="hero" id="top"><div class="wrap">
{rating}<h1>{e(content.get("headline"))}</h1>
<p class="sub">{e(content.get("subheadline"))}</p>
<div class="btns">{''.join(buttons)}</div>
</div></header>
<section id="services"><div class="wrap"><h2>Services</h2><div class="grid">{services}</div></div></section>
<section class="alt"><div class="wrap"><h2>Why choose us</h2><ul class="why">{why}</ul></div></section>
<section id="about"><div class="wrap about">
<div><h2>About {name}</h2><p>{e(content.get("about"))}</p></div>
<div class="card"><h3>{e(content.get("cta") or "Contact us")}</h3><p>{'Call us at <a href="tel:' + e(tel) + '">' + e(phone) + '</a> or send us a message.' if tel else 'Send us a message and we&#39;ll get back to you.'}</p><div class="btns">{buttons[0]}</div></div>
</div></section>
{gallery}
<section id="faq" class="alt"><div class="wrap"><h2>Frequently asked questions</h2>{faq}</div></section>
<section id="contact"><div class="wrap"><h2>Visit or contact us</h2><div class="contact">
<div>{contact_lines}<div class="btns">{''.join(buttons)}</div></div>
<iframe src="{e(map_embed)}" loading="lazy" title="Map"></iframe>
</div></div></section>
<div class="cta-band"><div class="wrap"><h2>{e(content.get("cta") or "Contact us")}</h2><div class="btns" style="justify-content:center">{buttons[0]}</div></div></div>
<footer><div class="wrap">© {name}{' · ' + e(city) if city else ''}</div></footer>
<div class="callbar">{buttons[0]}{buttons[-1] if len(buttons) > 1 else ''}</div>
</body></html>
"""


def build_preview(lead: dict, sender: dict, notes: str = "", photos: list[str] | None = None,
                  facebook_url: str = "", language: str = "English", client=None) -> tuple[str, str]:
    """Return (html, source) where source is 'claude' or 'template'."""
    content = claude_content(lead, notes, language, client) if client is not None else None
    source = "claude" if content else "template"
    content = content or default_content(lead, notes)
    return render_preview(lead, content, sender, photos, facebook_url), source
