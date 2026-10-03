"""One-page visual audit report, the "show, don't tell" asset linked from each email."""

from __future__ import annotations

import re
from html import escape

from .audit import AuditResult

IMPACT_LABEL = {3: "Costing you customers", 2: "Hurting trust & ranking", 1: "Quick win"}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "lead"


def render_report(lead: dict, audit: AuditResult, sender: dict) -> str:
    name = escape(lead.get("name") or audit.url)
    site = escape(audit.final_url or audit.url)
    score = audit.score
    grade_class = "bad" if score < 50 else "ok" if score < 80 else "good"
    items = "\n".join(
        f"""<li class="f i{f.impact}">
  <span class="tag">{IMPACT_LABEL[f.impact]}</span>
  <h3>{escape(f.title)}</h3>
  <p>{escape(f.detail)}</p>
  <p class="fix"><b>Fix:</b> {escape(f.fix)}</p>
</li>""" for f in audit.findings) or "<li class='f'><h3>No major issues found.</h3></li>"
    sender_name = escape(sender.get("name", ""))
    company = escape(sender.get("company", ""))
    contact = escape(sender.get("email", ""))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Website check: {name}</title>
<style>
:root{{--bg:#f7f7f5;--card:#fff;--ink:#1b1b1b;--mute:#5d5d5d;--line:#e4e4e0;
--bad:#c0392b;--ok:#b9770e;--good:#1e8449;--accent:#2457d6}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151515;--card:#1f1f1f;--ink:#eee;--mute:#aaa;
--line:#333;--bad:#ff6b5b;--ok:#f5b041;--good:#58d68d;--accent:#7ea2ff}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
main{{max-width:760px;margin:0 auto;padding:32px 16px 64px}}
header{{display:flex;gap:20px;align-items:center;flex-wrap:wrap}}
.score{{width:96px;height:96px;border-radius:50%;display:grid;place-items:center;
font-size:32px;font-weight:700;border:6px solid currentColor;flex:none}}
.bad{{color:var(--bad)}}.ok{{color:var(--ok)}}.good{{color:var(--good)}}
h1{{margin:0;font-size:26px}}.sub{{color:var(--mute);margin:4px 0 0;word-break:break-all}}
ul{{list-style:none;padding:0;margin:28px 0 0;display:grid;gap:12px}}
.f{{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--line);
border-radius:10px;padding:14px 16px}}.i3{{border-left-color:var(--bad)}}
.i2{{border-left-color:var(--ok)}}.i1{{border-left-color:var(--good)}}
.f h3{{margin:4px 0;font-size:18px}}.f p{{margin:4px 0;color:var(--mute)}}
.tag{{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--mute)}}
.fix{{color:var(--ink)!important}}
.cta{{margin-top:28px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px}}
.cta a{{color:var(--accent)}}footer{{margin-top:28px;font-size:13px;color:var(--mute)}}
</style></head>
<body><main>
<header>
  <div class="score {grade_class}" aria-label="Score {score} out of 100">{score}</div>
  <div><h1>{name}: website check</h1><p class="sub">{site}</p></div>
</header>
<p>We looked at your homepage the way a new customer on a phone would. Here's
what's most likely costing you calls and bookings, most expensive first.</p>
<ul>
{items}
</ul>
<div class="cta">
  <b>Want to see the fixed version?</b> We'll mock up your new homepage for free.
  Just reply to the email{f' or write to <a href="mailto:{contact}">{contact}</a>' if contact else ''}.
</div>
<footer>Prepared by {sender_name}{', ' + company if company else ''}. This check uses only
public information on your homepage.</footer>
</main></body></html>
"""
