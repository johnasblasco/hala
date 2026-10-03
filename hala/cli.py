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

from .audit import audit
from .pitch import write_pitch
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

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
