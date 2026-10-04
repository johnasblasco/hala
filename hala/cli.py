"""Command line entry point.

    hala audit https://example.com
    hala run leads.csv --out out/
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import find as finder
from .audit import audit
from .pitch import no_website_message, write_pitch
from .qualify import qualify
from .report import render_report, slugify

CAMPAIGN_FIELDS = ["tier", "score", "name", "email", "website", "category", "city",
                   "site_score", "top_issue", "angle", "subject", "body", "report_url",
                   "pitch_source", "reasons"]


def sender_from_env() -> dict:
    return {
        "name": os.environ.get("HALA_SENDER_NAME", ""),
        "company": os.environ.get("HALA_SENDER_COMPANY", ""),
        "email": os.environ.get("HALA_SENDER_EMAIL", ""),
        "address": os.environ.get("HALA_SENDER_ADDRESS", ""),
    }


def cmd_audit(args) -> int:
    result = audit(args.url)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0
    print(f"{result.url}  score {result.score}/100")
    for f in result.findings:
        print(f"  [{'!' * f.impact:<3}] {f.title}\n        {f.fix}")
    return 0


def cmd_run(args) -> int:
    sender = sender_from_env()
    if not (sender["name"] and sender["address"]):
        print("warning: set HALA_SENDER_NAME and HALA_SENDER_ADDRESS; anti-spam laws "
              "require sender identity and a physical address in every email.",
              file=sys.stderr)

    with open(args.leads, newline="", encoding="utf-8-sig") as fh:
        leads = [row for row in csv.DictReader(fh) if (row.get("website") or "").strip()]
    if not leads:
        print("no leads with a website column found", file=sys.stderr)
        return 1

    out = Path(args.out)
    (out / "reports").mkdir(parents=True, exist_ok=True)
    base_url = (args.report_base_url or os.environ.get("HALA_REPORT_BASE_URL", "")).rstrip("/")

    print(f"auditing {len(leads)} sites...", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        audits = list(pool.map(lambda l: audit(l["website"].strip()), leads))

    scored = sorted(
        ((qualify(lead, a), lead, a) for lead, a in zip(leads, audits)),
        key=lambda t: -t[0].score,
    )
    kept = [t for t in scored if t[0].tier != "skip"][: args.limit]

    rows = []
    for q, lead, a in kept:
        slug = slugify(lead.get("name") or a.url)
        (out / "reports" / f"{slug}.html").write_text(
            render_report(lead, a, sender), encoding="utf-8")
        report_url = f"{base_url}/{slug}.html" if base_url else f"reports/{slug}.html"
        pitch = write_pitch(lead, a, report_url, sender, use_claude=not args.no_ai)
        rows.append({
            "tier": q.tier, "score": q.score, "name": lead.get("name", ""),
            "email": lead.get("email", ""), "website": lead.get("website", ""),
            "category": lead.get("category", ""), "city": lead.get("city", ""),
            "site_score": a.score, "top_issue": a.top_finding.id if a.top_finding else "",
            "angle": pitch.angle, "subject": pitch.subject, "body": pitch.body,
            "report_url": report_url, "pitch_source": pitch.source,
            "reasons": "; ".join(q.reasons),
        })

    with open(out / "campaign.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPAIGN_FIELDS)
        w.writeheader()
        w.writerows(rows)

    skipped = len(scored) - len([t for t in scored if t[0].tier != "skip"])
    tiers = {t: sum(r["tier"] == t for r in rows) for t in "ABC"}
    print(f"wrote {len(rows)} leads to {out / 'campaign.csv'} "
          f"(A={tiers['A']} B={tiers['B']} C={tiers['C']}, skipped {skipped})",
          file=sys.stderr)
    return 0


def cmd_find(args) -> int:
    source = args.source
    if source == "auto":
        source = "google" if finder.api_key_from_env() else "osm"
    if source == "google":
        key = finder.api_key_from_env()
        if not key:
            print("error: set GOOGLE_MAPS_API_KEY, or use --source osm (free)", file=sys.stderr)
            return 1
        search = finder.google_search(key)
        print(f"searching Google Maps for: {', '.join(dict.fromkeys(args.queries))}", file=sys.stderr)
    else:
        search = finder.osm_search()
        print(f"searching OpenStreetMap (free) for: {', '.join(dict.fromkeys(args.queries))}", file=sys.stderr)
    try:
        queries = list(dict.fromkeys(q.strip() for q in args.queries if q.strip()))
        with_site, no_site = finder.find_leads(queries, search, args.max, args.workers)
    except (RuntimeError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finder.write_leads(args.out, with_site)
    found = sum(1 for l in with_site if l["email"])
    print(f"wrote {len(with_site)} businesses to {args.out} ({found} with an email found)",
          file=sys.stderr)
    if no_site:
        no_site_path = str(Path(args.out).with_name(Path(args.out).stem + "-no-website.csv"))
        sender = sender_from_env()
        for lead in no_site:
            lead["facebook_search"] = finder.facebook_search_url(lead)
            lead["message"] = no_website_message(lead, sender)
        finder.write_leads(no_site_path, no_site, finder.NO_SITE_FIELDS)
        print(f"wrote {len(no_site)} businesses with NO website to {no_site_path}\n"
              "  -> each has a ready-to-send Messenger/SMS message and a Facebook search link",
              file=sys.stderr)
    if args.run and not with_site:
        print("nothing to audit: none of these businesses list a website. "
              f"Start with {Path(args.out).stem}-no-website.csv instead.", file=sys.stderr)
        return 0
    if args.run:
        return cmd_run(argparse.Namespace(
            leads=args.out, out=args.run_out, limit=50, workers=args.workers,
            report_base_url=args.report_base_url, no_ai=args.no_ai))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hala", description="Audit, qualify and pitch local business websites.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("audit", help="audit one website")
    a.add_argument("url")
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_audit)

    r = sub.add_parser("run", help="full pipeline over a leads CSV")
    r.add_argument("leads", help="CSV with name,email,website[,category,city,reviews,rating,runs_ads,contact_name,language]")
    r.add_argument("--out", default="out")
    r.add_argument("--limit", type=int, default=50, help="max leads to keep (best first)")
    r.add_argument("--workers", type=int, default=8)
    r.add_argument("--report-base-url", help="public URL where out/reports/ will be hosted")
    r.add_argument("--no-ai", action="store_true", help="use the template instead of Claude")
    r.set_defaults(func=cmd_run)

    f = sub.add_parser("find", help="find leads on Google Maps and look up their emails")
    f.add_argument("queries", nargs="+", help='e.g. "dentist in Quezon City" "dentist in Makati"')
    f.add_argument("--out", default="leads.csv")
    f.add_argument("--source", choices=["auto", "osm", "google"], default="auto",
                   help="osm = free OpenStreetMap; google = Places API (needs key); "
                        "auto = google if GOOGLE_MAPS_API_KEY is set, else osm")
    f.add_argument("--max", type=int, default=60, help="max businesses per search (Google caps at 60)")
    f.add_argument("--workers", type=int, default=8)
    f.add_argument("--run", action="store_true", help="run the full pipeline right after")
    f.add_argument("--run-out", default="out", help="output folder when using --run")
    f.add_argument("--report-base-url")
    f.add_argument("--no-ai", action="store_true")
    f.set_defaults(func=cmd_find)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
