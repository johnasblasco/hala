"""Outreach copy: one short, specific, compliant email per qualified lead.

Uses Claude when an API credential is available and falls back to a
deterministic template otherwise. The compliance footer (sender identity,
address, opt-out) is always appended in code and never left to the model.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .audit import AuditResult

MODEL = "claude-opus-5-5"

SYSTEM = """You write cold emails for a small web studio that rebuilds websites for local businesses.

Rules:
- Under 110 words in the body. Plain text. No links except the report URL you are given.
- Open with one specific, observable fact about THEIR site, framed as lost customers or calls, not as criticism. Never insult the site or whoever built it.
- Mention exactly one problem (the most expensive one). The report link covers the rest.
- Offer something concrete and low-friction: a free mockup of their new homepage.
- End with a yes/no question. No "hope this finds you well", no fake urgency, no "Re:" or "Fwd:" subjects, no exclamation marks.
- Subject: under 6 words, lowercase is fine, specific to the business.
- Do not write a signature or an unsubscribe line; those are added later.
- Write in the language given in `language`."""

PITCH_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "angle": {"type": "string", "description": "2-4 word label for the hook used, for A/B tracking"},
    },
    "required": ["subject", "body", "angle"],
    "additionalProperties": False,
}


@dataclass
class Pitch:
    subject: str
    body: str
    angle: str
    source: str  # "claude" or "template"


def compliance_footer(sender: dict) -> str:
    lines = [f"{sender.get('name', '')}", sender.get("company", ""), sender.get("address", "")]
    footer = "\n".join(l for l in lines if l)
    return (f"{footer}\n\nNot interested? Reply \"no thanks\" and you won't hear "
            "from us again.")


def template_pitch(lead: dict, audit: AuditResult, report_url: str) -> Pitch:
    name = lead.get("name") or "there"
    f = audit.top_finding
    issue = (f.title[0].lower() + f.title[1:]).rstrip(".") if f else "a few things on your site cost you enquiries"
    greeting = lead.get("contact_name") or f"{name} team"
    body = (f"Hi {greeting},\n\n"
            f"I was looking at {name}'s website on my phone and noticed {issue}. "
            "For a local business, that usually means calls going to a competitor instead.\n\n"
            f"I put the details, plus a few quick wins, on one page: {report_url}\n\n"
            "If it's useful, I can mock up what a new homepage would look like, free and "
            "with no call needed. Want me to send it over?")
    return Pitch(subject=f"{name}: quick website note"[:60], body=body,
                 angle=f.id if f else "general", source="template")


def _has_credentials() -> bool:
    return any(os.environ.get(k) for k in
               ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"))


def claude_pitch(lead: dict, audit: AuditResult, report_url: str, client=None) -> Pitch | None:
    """Return a Claude-written pitch, or None if Claude is unavailable or declines."""
    import anthropic

    client = client or anthropic.Anthropic()
    facts = {
        "business": lead.get("name"),
        "category": lead.get("category"),
        "city": lead.get("city"),
        "contact_name": lead.get("contact_name"),
        "language": lead.get("language") or "English",
        "report_url": report_url,
        "findings": [{"title": f.title, "detail": f.detail, "impact": f.impact}
                     for f in audit.findings[:4]],
    }
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            output_config={"effort": "medium",
                           "format": {"type": "json_schema", "schema": PITCH_SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": json.dumps(facts, ensure_ascii=False)}],
        )
    except anthropic.APIError:
        return None
    if response.stop_reason in ("refusal", "max_tokens"):
        return None
    text = "".join(b.text for b in response.content if b.type == "text")
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return Pitch(subject=data["subject"], body=data["body"], angle=data["angle"], source="claude")


def write_pitch(lead: dict, audit: AuditResult, report_url: str, sender: dict,
                use_claude: bool = True) -> Pitch:
    pitch = None
    if use_claude and _has_credentials():
        pitch = claude_pitch(lead, audit, report_url)
    pitch = pitch or template_pitch(lead, audit, report_url)
    pitch.body = f"{pitch.body.rstrip()}\n\n{compliance_footer(sender)}"
    return pitch


CUSTOMER_WORD = {"dentist": "patients", "dental": "patients", "clinic": "patients",
                 "doctor": "patients", "veterinary": "pet owners", "vet": "pet owners",
                 "hotel": "guests", "resort": "guests", "guest house": "guests",
                 "lawyer": "clients", "accountant": "clients", "school": "parents"}


def no_website_message(lead: dict, sender: dict) -> str:
    """Short Messenger/SMS opener for a business that has no website at all."""
    name = lead.get("name") or "there"
    category = (lead.get("category") or "").lower()
    who = next((w for k, w in CUSTOMER_WORD.items() if k in category), "customers")
    kind = category or "business"
    where = f" in {lead['city']}" if lead.get("city") else ""
    me = sender.get("name") or "a local web designer"
    return (f"Hi {name}! I'm {me}, a web designer. I noticed you don't have a website yet, "
            f"so {who} searching Google for a {kind}{where} are finding other places first. "
            "I can build you a simple, mobile-friendly site with tap-to-call and directions, "
            "and show you a free preview before you decide anything. Would you like to see it? "
            "If not, no worries, I won't message again.")
