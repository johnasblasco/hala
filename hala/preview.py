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

from .ai import AnthropicWriter, Writer

LANGUAGES = ("English", "Filipino", "Taglish", "Spanish", "Portuguese", "French", "German", "Italian",
             "Dutch", "Indonesian", "Malay", "Vietnamese", "Thai", "Japanese", "Korean",
             "Chinese (Simplified)", "Arabic", "Hindi")

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

SYSTEM = """You write the text for a one-page website preview for a small local business (its country is given in `country`). A web designer will show it to the owner as "here's what your site could look like".

Rules:
- Use ONLY facts given to you. Never invent prices, years in business, awards, certifications, staff or doctor names, testimonials, statistics or promotions. If you don't know something, write around it.
- If the owner's notes list services, hours or specialties, use them. Otherwise use typical services for this kind of business, phrased generally.
- headline: under 9 words, benefit-led, can mention the town. subheadline: one sentence.
- 4 to 6 services, each with a one-sentence description. 3 short "why choose us" points that don't make unverifiable claims (e.g. "Easy to reach in <town>", "Book by call or message").
- about: 2 to 3 warm sentences. faq: 3 practical questions (booking, location, payment or what to bring) with answers that don't invent facts; when unsure, say to call or message.
- cta: a short button label like "Book an appointment".
- Write in the language given in `language` (Taglish = natural Filipino-English mix).
- Match the business's country: local spelling, currency words and phrasing; never assume the Philippines unless the address says so."""


# Rotated so cards don't repeat; deliberately claim nothing specific.
GENERIC_DESCRIPTIONS = [
    "Done with care and attention to detail, at a pace that's comfortable for you.",
    "Tell us what you need and we'll walk you through the options.",
    "Convenient schedules. Call or message us to book.",
    "A friendly team that takes the time to answer your questions.",
    "Clear advice before we start, so you know what to expect.",
    "Ask us about availability and we'll find a time that works.",
]


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
        "services": [{"name": s, "description": GENERIC_DESCRIPTIONS[i % len(GENERIC_DESCRIPTIONS)]}
                     for i, s in enumerate(services[:6])],
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


def ai_content(lead: dict, notes: str, language: str, writer: Writer) -> dict | None:
    """Ask the AI provider for the page text. Returns None if it fails or declines."""
    kind = business_type(lead)
    facts = {
        "business_name": lead.get("name"),
        "type": lead.get("category") or kind,
        "town": lead.get("city"),
        "country": lead.get("country") or None,
        "address": lead.get("address"),
        "google_rating": lead.get("rating") or None,
        "review_count": lead.get("reviews") or None,
        "owner_notes": notes or None,
        "typical_services_hint": DEFAULTS.get(kind, (None, None))[1],
        "language": language if language in LANGUAGES else "English",
    }
    data = writer.generate(SYSTEM, json.dumps(facts, ensure_ascii=False), CONTENT_SCHEMA, "low")
    if not data or not data.get("services"):
        return None
    return data


def claude_content(lead: dict, notes: str, language: str, client) -> dict | None:
    return ai_content(lead, notes, language, AnthropicWriter(client=client))


# --- page ------------------------------------------------------------------

# Font pairing per business type: (heading family, Google Fonts query, style).
SANS_FALLBACK = "system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
SERIF_FALLBACK = "ui-serif,Georgia,'Times New Roman',serif"
FONT_SANS = (f"'Plus Jakarta Sans',{SANS_FALLBACK}", "Plus+Jakarta+Sans:wght@500;600;700;800")
FONT_SERIF = (f"'Fraunces',{SERIF_FALLBACK}", "Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700")
FONT_ELEGANT = (f"'Cormorant Garamond',{SERIF_FALLBACK}", "Cormorant+Garamond:wght@500;600;700")
FONTS_BY_TYPE = {"salon": FONT_ELEGANT, "spa": FONT_ELEGANT, "resort": FONT_SERIF,
                 "restaurant": FONT_SERIF, "cafe": FONT_SERIF, "lawyer": FONT_SERIF,
                 "accountant": FONT_SERIF, "real estate": FONT_SERIF}

# Minimal stroke icons (24x24, currentColor). Picked by keyword in a service name.
ICONS = {
    "tooth": '<path d="M7 3c-2.5 0-4 2-4 4.5 0 3 1.5 4.5 2 7 .5 3 1 6.5 2.5 6.5S9 18 10 16c.6-1.2 1.4-1.2 2 0 1 2 1 5 2.5 5S16.5 17.5 17 14.5c.5-2.5 2-4 2-7C19 5 17.5 3 15 3c-1.6 0-2.4 1-4 1S8.6 3 7 3z"/>',
    "sparkle": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/>',
    "heart": '<path d="M12 20s-7-4.4-9-9.2C1.6 7.2 4 4 7.2 4c2 0 3.4 1.1 4.8 3 1.4-1.9 2.8-3 4.8-3C20 4 22.4 7.2 21 10.8 19 15.6 12 20 12 20z"/>',
    "scissors": '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M8.6 7.6L20 18M8.6 16.4L20 6"/>',
    "leaf": '<path d="M5 21c0-9 5-15 16-16-1 11-7 16-16 16z"/><path d="M5 21l8-8"/>',
    "wrench": '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.2L3 17.8V21h3.2l6.3-6.3a4 4 0 0 0 5.2-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/>',
    "home": '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    "scale": '<path d="M12 3v18M5 7h14M5 7l-3 7a3 3 0 0 0 6 0zM19 7l-3 7a3 3 0 0 0 6 0zM8 21h8"/>',
    "book": '<path d="M4 4h6a2 2 0 0 1 2 2v14a2 2 0 0 0-2-2H4zM20 4h-6a2 2 0 0 0-2 2v14a2 2 0 0 1 2-2h6z"/>',
    "dumbbell": '<path d="M6 7v10M3 9v6M18 7v10M21 9v6M6 12h12"/>',
    "paw": '<circle cx="5.5" cy="10" r="2"/><circle cx="9" cy="5.5" r="2"/><circle cx="15" cy="5.5" r="2"/><circle cx="18.5" cy="10" r="2"/><path d="M12 11c-3 0-6 4.5-6 7 0 2 2 3 6 3s6-1 6-3c0-2.5-3-7-6-7z"/>',
    "cup": '<path d="M4 8h13v5a6 6 0 0 1-6 6h-1a6 6 0 0 1-6-6z"/><path d="M17 9h1.5a2.5 2.5 0 0 1 0 5H17M8 3v2M12 3v2"/>',
    "plate": '<circle cx="12" cy="12" r="6"/><path d="M3 4v6a2 2 0 0 0 2 2M5 4v16M21 4v16M21 4c-2 1-3 3-3 6s1 4 3 4"/>',
    "bed": '<path d="M3 18V7M3 12h18v6M21 18v-3M7 12V9h5v3"/>',
    "wave": '<path d="M2 15c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2M2 19c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2"/><circle cx="17" cy="6" r="3"/>',
    "shield": '<path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.5 2.5L16 9.5"/>',
    "pin": '<path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
    "phone": '<path d="M5 3h3l2 5-2.5 1.5a11 11 0 0 0 7 7L16 14l5 2v3a2 2 0 0 1-2 2A17 17 0 0 1 3 5a2 2 0 0 1 2-2z"/>',
    "chat": '<path d="M4 5h16v11H9l-5 4z"/>',
    "star": '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>',
}
ICON_KEYWORDS = [
    (("brace", "align", "tooth", "teeth", "dent", "root canal", "extraction", "filling", "crown",
      "implant", "ngipin"), "tooth"),
    (("whiten", "clean", "facial", "beauty", "glow", "make-up", "makeup", "polish", "styling"), "sparkle"),
    (("check-up", "checkup", "consult", "appointment", "booking", "schedule"), "calendar"),
    (("kid", "child", "family", "pediatric", "care", "therapy"), "heart"),
    (("hair", "cut", "rebond", "keratin", "barber", "color"), "scissors"),
    (("massage", "spa", "scrub", "relax", "reflex", "wellness"), "leaf"),
    (("oil", "brake", "engine", "repair", "tune", "aircon", "electrical", "suspension", "paint"), "wrench"),
    (("house", "condo", "lot", "rental", "property", "home"), "home"),
    (("legal", "law", "contract", "notar", "litigation", "corporate"), "scale"),
    (("tax", "bookkeep", "payroll", "financial", "audit", "registration", "tutor", "school",
      "class", "enroll", "preschool", "elementary"), "book"),
    (("gym", "training", "fitness", "strength", "weight", "membership"), "dumbbell"),
    (("pet", "vet", "groom", "deworm", "vaccin"), "paw"),
    (("coffee", "drink", "pastr", "snack"), "cup"),
    (("dine", "food", "meal", "cater", "take-out", "delivery", "special"), "plate"),
    (("room", "overnight", "stay", "function hall", "event"), "bed"),
    (("pool", "day tour", "beach", "swim"), "wave"),
]


def icon(name: str, size: int = 24) -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            f'{ICONS.get(name, ICONS["check"])}</svg>')


def icon_for(service_name: str, kind: str) -> str:
    text = (service_name or "").lower()
    for words, name in ICON_KEYWORDS:
        if any(w in text for w in words):
            return name
    return {"dentist": "tooth", "salon": "scissors", "spa": "leaf", "auto repair": "wrench",
            "vet": "paw", "gym": "dumbbell", "lawyer": "scale", "cafe": "cup",
            "restaurant": "plate", "resort": "wave", "real estate": "home"}.get(kind, "check")


def initials(name: str) -> str:
    words = [w for w in re.split(r"[^\w]+", name or "") if w and w[0].isalnum()]
    letters = "".join(w[0] for w in words[:2]).upper()
    return letters or "•"


STEPS = {
    "default": [("chat", "Message or call", "Tell us what you need. We usually reply the same day."),
                ("calendar", "Pick a schedule", "We'll find a time that works for you."),
                ("pin", "Visit us", "Drop by. Directions are one tap away.")],
    "resort": [("chat", "Send an inquiry", "Ask about dates, rates and packages."),
               ("calendar", "Reserve your date", "We'll confirm your booking."),
               ("wave", "Enjoy your stay", "Relax. We'll take care of the rest.")],
    "restaurant": [("chat", "Message or call", "Ask about the menu, reservations or orders."),
                   ("calendar", "Reserve or order", "Dine in, take out or have it delivered."),
                   ("plate", "Enjoy", "Good food, served with care.")],
}

PAGE_CSS = """
:root{--a:__A__;--d:__D__;--s:__S__;--ink:#121417;--body:#3b4048;--mute:#6b7280;--line:#e7e8ec;
--bg:#ffffff;--bg2:#f7f7f5;--r:20px;--shadow:0 1px 2px rgba(16,24,40,.04),0 12px 32px -12px rgba(16,24,40,.14);
--hf:__HF__;--bf:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:96px;-webkit-text-size-adjust:100%}
body{margin:0;font:16.5px/1.65 var(--bf);color:var(--body);background:var(--bg);-webkit-font-smoothing:antialiased}
img{max-width:100%;display:block}a{color:inherit}
h1,h2,h3{font-family:var(--hf);color:var(--ink);line-height:1.12;margin:0;letter-spacing:-.02em;font-weight:700}
h1{font-size:clamp(38px,5.6vw,64px)}h2{font-size:clamp(30px,3.8vw,44px)}h3{font-size:20px;letter-spacing:-.01em}
.wrap{max-width:1160px;margin:0 auto;padding:0 24px}
.eyebrow{display:inline-flex;align-items:center;gap:8px;font:600 13px/1 var(--bf);letter-spacing:.08em;text-transform:uppercase;color:var(--a)}
.eyebrow::before{content:"";width:22px;height:2px;background:currentColor;border-radius:2px}
.lead{font-size:clamp(17px,1.6vw,19.5px);color:var(--mute);max-width:560px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:10px;padding:15px 24px;border-radius:999px;
font:600 15.5px/1 var(--bf);text-decoration:none;border:1px solid transparent;transition:transform .2s ease,box-shadow .2s ease,background .2s ease;white-space:nowrap}
.btn:hover{transform:translateY(-1px)}.btn:focus-visible,a:focus-visible,summary:focus-visible{outline:3px solid var(--a);outline-offset:3px}
.btn-primary{background:var(--a);color:#fff;box-shadow:0 10px 24px -10px var(--a)}
.btn-primary:hover{background:var(--d)}
.btn-ghost{background:#fff;color:var(--ink);border-color:var(--line)}
.btn-ghost:hover{border-color:var(--ink)}
.ribbon{background:#0f1115;color:#c9ccd3;font-size:12.5px;text-align:center;padding:7px 16px;letter-spacing:.01em}
.ribbon b{color:#fff;font-weight:600}
nav{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.82);backdrop-filter:saturate(1.6) blur(14px);-webkit-backdrop-filter:saturate(1.6) blur(14px);border-bottom:1px solid rgba(0,0,0,.06)}
nav .wrap{display:flex;align-items:center;justify-content:space-between;height:72px;gap:16px}
.brand{display:flex;align-items:center;gap:12px;text-decoration:none;min-width:0}
.mono{width:40px;height:40px;border-radius:12px;display:grid;place-items:center;background:var(--a);color:#fff;font:700 15px/1 var(--bf);letter-spacing:.02em;flex:none}
.brand .bname{font:700 17px/1.2 var(--hf);color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.navlinks{display:flex;gap:28px;align-items:center}.navlinks a{text-decoration:none;color:var(--body);font-size:15px;font-weight:500}
.navlinks a:hover{color:var(--ink)}nav .btn{padding:11px 18px;font-size:14.5px}
.navlinks a.btn-primary,.navlinks a.btn-primary:hover{color:#fff}
.hero{position:relative;overflow:hidden;padding:84px 0 96px;background:
radial-gradient(900px 480px at 85% -10%,var(--s),transparent 60%),radial-gradient(700px 400px at -10% 110%,var(--s),transparent 60%),var(--bg)}
.hero-grid{display:grid;grid-template-columns:1.08fr .92fr;gap:56px;align-items:center}
.hero h1{margin:18px 0 20px}.hero h1 em{font-style:normal;color:var(--a)}
.hero .btns{display:flex;flex-wrap:wrap;gap:12px;margin-top:32px}
.trust{display:flex;flex-wrap:wrap;gap:22px;margin-top:36px;color:var(--mute);font-size:14.5px}
.trust span{display:inline-flex;align-items:center;gap:8px}.trust svg{color:var(--a)}
.stars{color:#f5a524;letter-spacing:1px}
.visual{position:relative;min-height:440px}
.photo{position:absolute;inset:0 0 40px 40px;border-radius:28px;overflow:hidden;box-shadow:var(--shadow);background:linear-gradient(140deg,var(--a),var(--d))}
.photo img{width:100%;height:100%;object-fit:cover}
.photo.art::before,.photo.art::after{content:"";position:absolute;border-radius:50%;filter:blur(2px);opacity:.55}
.photo.art::before{width:320px;height:320px;right:-80px;top:-60px;background:radial-gradient(circle at 30% 30%,rgba(255,255,255,.55),transparent 65%)}
.photo.art::after{width:260px;height:260px;left:-60px;bottom:-80px;background:radial-gradient(circle at 60% 40%,rgba(255,255,255,.35),transparent 65%)}
.photo .bigmono{position:absolute;inset:0;display:grid;place-items:center;font:700 120px/1 var(--hf);color:rgba(255,255,255,.18);letter-spacing:-.04em}
.float{position:absolute;left:0;bottom:0;width:min(340px,86%);background:#fff;border-radius:22px;padding:22px;box-shadow:0 24px 48px -16px rgba(16,24,40,.28);border:1px solid var(--line)}
.float h3{font-size:17px;margin-bottom:12px}.float ul{list-style:none;margin:0;padding:0;display:grid;gap:12px}
.float li{display:flex;gap:12px;align-items:flex-start;font-size:14.5px;line-height:1.45}
.float li svg{flex:none;color:var(--a);margin-top:1px}.float a{color:var(--ink);font-weight:600;text-decoration:none}
.float .flink{display:inline-block;margin-top:16px;color:var(--a);font-weight:600;font-size:14.5px;text-decoration:none}
.float .flink:hover{text-decoration:underline}
.chip{display:inline-flex;align-items:center;gap:8px;position:absolute;right:16px;top:20px;background:#fff;border-radius:999px;padding:9px 14px;font-size:13.5px;font-weight:600;color:var(--ink);box-shadow:var(--shadow)}
section{padding:104px 0}.alt{background:var(--bg2)}
.sec-head{max-width:640px;margin-bottom:52px}.sec-head h2{margin-top:14px}.sec-head p{margin:16px 0 0;color:var(--mute);font-size:17.5px}
.center{text-align:center;margin-left:auto;margin-right:auto}
.strip{padding:0;margin-top:-44px;position:relative;z-index:2}
.strip .wrap>div{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1px;background:var(--line);border:1px solid var(--line);border-radius:var(--r);overflow:hidden;box-shadow:var(--shadow)}
.strip .item{background:#fff;padding:24px 26px;display:flex;gap:14px;align-items:center;font-weight:600;color:var(--ink);font-size:15.5px}
.strip .item i{width:42px;height:42px;border-radius:12px;background:var(--s);color:var(--a);display:grid;place-items:center;flex:none}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px}
.card{background:#fff;border:1px solid var(--line);border-radius:var(--r);padding:30px;transition:transform .25s ease,box-shadow .25s ease,border-color .25s ease}
.card:hover{transform:translateY(-4px);box-shadow:var(--shadow);border-color:transparent}
.card i{width:52px;height:52px;border-radius:16px;background:var(--s);color:var(--a);display:grid;place-items:center;margin-bottom:22px}
.card p{margin:10px 0 0;color:var(--mute);font-size:15.5px}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;counter-reset:step}
.step{position:relative;padding:32px;border-radius:var(--r);background:#fff;border:1px solid var(--line)}
.step::before{counter-increment:step;content:"0" counter(step);position:absolute;right:26px;top:22px;font:700 44px/1 var(--hf);color:var(--s)}
.step i{color:var(--a);display:block;margin-bottom:18px}.step p{margin:10px 0 0;color:var(--mute);font-size:15.5px}
.about{display:grid;grid-template-columns:1fr 1fr;gap:64px;align-items:center}
.about blockquote{margin:24px 0 0;font:500 clamp(20px,2vw,24px)/1.5 var(--hf);color:var(--ink);letter-spacing:-.01em}
.facts{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
.fact{background:#fff;border:1px solid var(--line);border-radius:var(--r);padding:26px}
.fact b{display:block;font:700 34px/1.1 var(--hf);color:var(--ink);letter-spacing:-.02em}.fact span{color:var(--mute);font-size:14.5px}
.fact.accent{background:linear-gradient(140deg,var(--a),var(--d));border-color:transparent}.fact.accent b,.fact.accent span{color:#fff}
.gallery{display:grid;grid-template-columns:repeat(4,1fr);grid-auto-rows:200px;gap:14px}
.gallery img{width:100%;height:100%;object-fit:cover;border-radius:16px}.gallery img:first-child{grid-column:span 2;grid-row:span 2}
.faq{display:grid;grid-template-columns:.8fr 1.2fr;gap:56px;align-items:start}
details{border-bottom:1px solid var(--line);padding:22px 0}details:first-child{border-top:1px solid var(--line)}
summary{list-style:none;cursor:pointer;display:flex;justify-content:space-between;gap:16px;font:600 17px/1.4 var(--bf);color:var(--ink)}
summary::-webkit-details-marker{display:none}
summary::after{content:"+";font:400 24px/1 var(--bf);color:var(--a);transition:transform .2s}
details[open] summary::after{transform:rotate(45deg)}details p{margin:12px 0 0;color:var(--mute)}
.cta{padding:0 0 104px}.cta .box{border-radius:32px;padding:72px 48px;text-align:center;color:#fff;position:relative;overflow:hidden;
background:radial-gradient(600px 300px at 15% 0%,rgba(255,255,255,.18),transparent 60%),linear-gradient(135deg,var(--a),var(--d))}
.cta h2{color:#fff;max-width:720px;margin:0 auto}.cta p{color:rgba(255,255,255,.85);margin:16px auto 32px;max-width:520px;font-size:17.5px}
.cta .btns{display:flex;gap:12px;justify-content:center;flex-wrap:wrap}
.cta .btn-primary{background:#fff;color:var(--d);box-shadow:none}.cta .btn-ghost{background:transparent;color:#fff;border-color:rgba(255,255,255,.45)}
.contact{display:grid;grid-template-columns:.9fr 1.1fr;gap:24px;align-items:stretch}
.info{background:#fff;border:1px solid var(--line);border-radius:var(--r);padding:34px;display:grid;gap:22px;align-content:start}
.info .row{display:flex;gap:16px}.info .row i{width:44px;height:44px;border-radius:12px;background:var(--s);color:var(--a);display:grid;place-items:center;flex:none}
.info small{display:block;color:var(--mute);font-size:13px;text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.info a,.info p{color:var(--ink);font-weight:600;text-decoration:none;margin:2px 0 0}
.map{border-radius:var(--r);overflow:hidden;border:1px solid var(--line);min-height:380px;background:var(--bg2)}
.map iframe{width:100%;height:100%;min-height:380px;border:0;display:block}
footer{border-top:1px solid var(--line);padding:36px 0;color:var(--mute);font-size:14px}
footer .wrap{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}
.callbar{display:none}
.reveal{opacity:1}
@media (prefers-reduced-motion:no-preference){.js .reveal{opacity:0;transform:translateY(18px);transition:opacity .7s ease,transform .7s ease}.js .reveal.in{opacity:1;transform:none}}
@media (max-width:960px){.hero-grid,.about,.faq,.contact{grid-template-columns:1fr}.visual{min-height:380px}.steps{grid-template-columns:1fr}
.navlinks a:not(.btn){display:none}.gallery{grid-template-columns:repeat(2,1fr)}}
@media (max-width:640px){body{font-size:16px;padding-bottom:78px}section{padding:72px 0}.hero{padding:48px 0 72px}.wrap{padding:0 20px}
nav .wrap{height:64px}nav .btn{display:none}.visual{min-height:340px}.photo{inset:0 0 56px 0}.float{left:12px;right:12px;width:auto}
.cta .box{padding:52px 24px;border-radius:24px}.strip{margin-top:-32px}.facts{grid-template-columns:1fr 1fr}
.callbar{display:flex;gap:10px;position:fixed;left:0;right:0;bottom:0;z-index:30;padding:12px 14px calc(12px + env(safe-area-inset-bottom));background:rgba(255,255,255,.94);backdrop-filter:blur(12px);border-top:1px solid var(--line)}
.callbar .btn{flex:1 1 0;min-width:0;padding:14px 10px;font-size:15px}
.hero .btns .btn{flex:1 1 100%}.hero .trust{gap:12px 18px}}
"""

REVEAL_JS = """<script>
document.documentElement.classList.add('js');
(function(){var els=document.querySelectorAll('.reveal');if(!('IntersectionObserver' in window)){els.forEach(function(e){e.classList.add('in')});return}
var io=new IntersectionObserver(function(entries){entries.forEach(function(en){if(en.isIntersecting){en.target.classList.add('in');io.unobserve(en.target)}})},{threshold:.12});
els.forEach(function(e){io.observe(e)})})();
</script>"""


def render_preview(lead: dict, content: dict, sender: dict, photos: list[str] | None = None,
                   facebook_url: str = "") -> str:
    accent, dark, soft = theme_for(lead)
    kind = business_type(lead)
    head_font, font_query = FONTS_BY_TYPE.get(kind, FONT_SANS)
    e = lambda s: escape(str(s or ""))  # noqa: E731
    raw_name = lead.get("name") or "Your Business"
    name = e(raw_name)
    city = lead.get("city") or ""
    address = lead.get("address") or ""
    full_address = ", ".join(x for x in (address, city) if x and (x not in address or x == address))
    phone = (lead.get("phone") or "").strip()
    tel = re.sub(r"[^\d+]", "", phone)
    photos = [p for p in (safe_url(u) for u in (photos or [])) if p][:7]
    fb = safe_url(facebook_url)
    place_q = quote_plus(" ".join(x for x in (raw_name, address, city) if x))
    directions = f"https://www.google.com/maps/search/?api=1&query={place_q}"
    map_embed = f"https://maps.google.com/maps?q={place_q}&output=embed"
    cta = e(content.get("cta") or "Contact us")
    label = e((lead.get("category") or kind or "Local business").title())

    # Primary action: call if we have a number, else Facebook, else directions.
    if tel:
        primary = (f'<a class="btn btn-primary" href="tel:{e(tel)}">{icon("phone", 18)} Call {e(phone)}</a>', "Call now",
                   f"tel:{e(tel)}")
    elif fb:
        primary = (f'<a class="btn btn-primary" href="{e(fb)}" target="_blank" rel="noopener">{icon("chat", 18)} Message us</a>',
                   "Message us", e(fb))
    else:
        primary = (f'<a class="btn btn-primary" href="{e(directions)}" target="_blank" rel="noopener">{icon("pin", 18)} Get directions</a>',
                   "Directions", e(directions))
    secondary = []
    if fb and tel:
        secondary.append(f'<a class="btn btn-ghost" href="{e(fb)}" target="_blank" rel="noopener">{icon("chat", 18)} Message on Facebook</a>')
    if tel or fb:
        secondary.append(f'<a class="btn btn-ghost" href="{e(directions)}" target="_blank" rel="noopener">{icon("pin", 18)} Get directions</a>')

    # Hero headline: highlight the town if it appears in it.
    headline = e(content.get("headline"))
    if city and e(city) in headline:
        headline = headline.replace(e(city), f"<em>{e(city)}</em>", 1)

    rating, reviews = lead.get("rating"), lead.get("reviews")
    trust = []
    if rating and reviews:
        trust.append(f'<span><span class="stars">★</span> {e(rating)} on Google · {e(reviews)} reviews</span>')
    if city:
        trust.append(f'<span>{icon("pin", 18)} Serving {e(city)}</span>')
    trust.append(f'<span>{icon("calendar", 18)} Easy booking</span>')

    float_items = []
    if full_address:
        float_items.append(f'<li>{icon("pin", 20)}<span>{e(full_address)}</span></li>')
    if tel:
        float_items.append(f'<li>{icon("phone", 20)}<a href="tel:{e(tel)}">{e(phone)}</a></li>')
    if fb:
        float_items.append(f'<li>{icon("chat", 20)}<a href="{e(fb)}" target="_blank" rel="noopener">Message us on Facebook</a></li>')
    float_items.append(f'<li>{icon("calendar", 20)}<span>Call or message to book a schedule</span></li>')

    if photos:
        visual_media = f'<div class="photo"><img src="{e(photos[0])}" alt="{name}" fetchpriority="high"></div>'
    else:
        visual_media = f'<div class="photo art"><div class="bigmono">{e(initials(raw_name))}</div></div>'
    chip = (f'<div class="chip"><span class="stars">★</span> {e(rating)} rating</div>' if rating else
            f'<div class="chip">{icon("shield", 16)} Trusted locally</div>')

    why = "".join(f'<div class="item"><i>{icon(["shield", "calendar", "heart", "star"][i % 4], 20)}</i>{e(w)}</div>'
                  for i, w in enumerate(content.get("why_us", [])[:4]))
    services = "".join(
        f'<article class="card reveal"><i>{icon(icon_for(s.get("name", ""), kind), 26)}</i>'
        f'<h3>{e(s.get("name"))}</h3><p>{e(s.get("description"))}</p></article>'
        for s in content.get("services", [])[:6])
    steps = "".join(f'<div class="step reveal"><i>{icon(ic, 30)}</i><h3>{e(t)}</h3><p>{e(d)}</p></div>'
                    for ic, t, d in STEPS.get(kind, STEPS["default"]))
    facts = []
    if rating:
        facts.append(f'<div class="fact accent"><b>★ {e(rating)}</b><span>Google rating</span></div>')
    if reviews:
        facts.append(f'<div class="fact"><b>{e(reviews)}</b><span>Google reviews</span></div>')
    facts.append(f'<div class="fact{" accent" if not rating else ""}"><b>{len(content.get("services", [])[:6])}</b>'
                 f'<span>Services offered</span></div>')
    if city:
        facts.append(f'<div class="fact"><b style="font-size:24px">{e(city)}</b><span>Location</span></div>')
    gallery = ""
    if len(photos) > 1:
        gallery = ('<section class="alt"><div class="wrap"><div class="sec-head reveal"><span class="eyebrow">Gallery</span>'
                   '<h2>Take a look inside</h2></div><div class="gallery reveal">' +
                   "".join(f'<img src="{e(p)}" alt="{name}" loading="lazy">' for p in photos[1:7]) +
                   "</div></div></section>")
    faq = "".join(f"<details><summary>{e(f.get('q'))}</summary><p>{e(f.get('a'))}</p></details>"
                  for f in content.get("faq", [])[:6])
    contact_rows = []
    if full_address:
        contact_rows.append(f'<div class="row"><i>{icon("pin", 20)}</i><div><small>Address</small><p>{e(full_address)}</p></div></div>')
    if tel:
        contact_rows.append(f'<div class="row"><i>{icon("phone", 20)}</i><div><small>Phone</small><a href="tel:{e(tel)}">{e(phone)}</a></div></div>')
    if fb:
        contact_rows.append(f'<div class="row"><i>{icon("chat", 20)}</i><div><small>Facebook</small><a href="{e(fb)}" target="_blank" rel="noopener">Send us a message</a></div></div>')
    contact_rows.append(f'<div class="row"><i>{icon("calendar", 20)}</i><div><small>Schedule</small><p>Call or message us for available times</p></div></div>')
    by = e(sender.get("name") or "a web designer")
    studio = e(sender.get("company") or "")
    css = (PAGE_CSS.replace("__A__", accent).replace("__D__", dark).replace("__S__", soft)
           .replace("__HF__", head_font))

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow">
<meta name="theme-color" content="{accent}">
<title>{name}{' · ' + e(city) if city else ''}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family={font_query}&display=swap" rel="stylesheet">
<style>{css}</style></head>
<body>
<div class="ribbon"><b>Design preview</b> for {name} · prepared by {by}{' · ' + studio if studio else ''} · not a live website</div>
<nav><div class="wrap">
<a class="brand" href="#top"><span class="mono">{e(initials(raw_name))}</span><span class="bname">{name}</span></a>
<div class="navlinks"><a href="#services">Services</a><a href="#about">About</a><a href="#faq">FAQ</a><a href="#contact">Contact</a>
<a class="btn btn-primary" href="{primary[2]}"{' target="_blank" rel="noopener"' if not tel else ''}>{primary[1]}</a></div>
</div></nav>

<header class="hero" id="top"><div class="wrap hero-grid">
<div class="reveal">
<span class="eyebrow">{label}{' · ' + e(city) if city else ''}</span>
<h1>{headline}</h1>
<p class="lead">{e(content.get("subheadline"))}</p>
<div class="btns">{primary[0]}{''.join(secondary[:1])}</div>
<div class="trust">{''.join(trust)}</div>
</div>
<div class="visual reveal">{visual_media}{chip}
<div class="float"><h3>Visit {name}</h3><ul>{''.join(float_items)}</ul>
<a class="flink" href="{e(directions)}" target="_blank" rel="noopener">Get directions →</a></div>
</div>
</div></header>

<div class="strip"><div class="wrap"><div>{why}</div></div></div>

<section id="services"><div class="wrap">
<div class="sec-head reveal"><span class="eyebrow">Services</span><h2>What we can do for you</h2>
<p>{e(content.get("subheadline"))}</p></div>
<div class="cards">{services}</div>
</div></section>

<section class="alt"><div class="wrap">
<div class="sec-head center reveal"><span class="eyebrow">How it works</span><h2>Simple from start to finish</h2></div>
<div class="steps">{steps}</div>
</div></section>

<section id="about"><div class="wrap about">
<div class="reveal"><span class="eyebrow">About us</span><h2 style="margin-top:14px">{name}</h2>
<blockquote>{e(content.get("about"))}</blockquote></div>
<div class="facts reveal">{''.join(facts)}</div>
</div></section>

{gallery}

<section id="faq" class="{'alt' if not gallery else ''}"><div class="wrap faq">
<div class="sec-head reveal" style="margin:0"><span class="eyebrow">FAQ</span><h2>Questions, answered</h2>
<p>Can't find what you're looking for? {'Call us at ' + e(phone) + '.' if tel else 'Send us a message.'}</p></div>
<div class="reveal">{faq}</div>
</div></section>

<div class="cta"><div class="wrap"><div class="box reveal">
<h2>{cta}</h2>
<p>We'd love to hear from you. Reach out and we'll get back to you as soon as we can.</p>
<div class="btns">{primary[0]}{''.join(secondary[:1])}</div>
</div></div></div>

<section id="contact" style="padding-top:0"><div class="wrap">
<div class="sec-head reveal"><span class="eyebrow">Contact</span><h2>Visit or get in touch</h2></div>
<div class="contact reveal"><div class="info">{''.join(contact_rows)}
<div><a class="btn btn-primary" href="{e(directions)}" target="_blank" rel="noopener">{icon("pin", 18)} Get directions</a></div></div>
<div class="map"><iframe src="{e(map_embed)}" loading="lazy" title="Map to {name}" referrerpolicy="no-referrer-when-downgrade"></iframe></div>
</div></div></section>

<footer><div class="wrap"><span>© {name}{' · ' + e(city) if city else ''}</span><span>Preview by {by}</span></div></footer>
<div class="callbar"><a class="btn btn-primary" href="{primary[2]}"{' target="_blank" rel="noopener"' if not tel else ''}>{icon("phone" if tel else "chat", 18)} {primary[1]}</a><a class="btn btn-ghost" href="{e(directions)}" target="_blank" rel="noopener">{icon("pin", 18)} Directions</a></div>
{REVEAL_JS}
</body></html>
"""


def build_preview(lead: dict, sender: dict, notes: str = "", photos: list[str] | None = None,
                  facebook_url: str = "", language: str = "English", client=None,
                  writer: Writer | None = None) -> tuple[str, str]:
    """Return (html, source) where source is the AI provider name or 'template'."""
    if writer is None and client is not None:
        writer = AnthropicWriter(client=client)
    content = ai_content(lead, notes, language, writer) if writer is not None else None
    source = writer.name if content else "template"
    content = content or default_content(lead, notes)
    return render_preview(lead, content, sender, photos, facebook_url), source
