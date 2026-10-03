# Hala

A small, self-owned pipeline for selling websites to local businesses. It
audits each site, qualifies the lead, builds a visual report page, and writes
outreach copy.

It's modelled on the "sold 200 websites in 12 months" playbook, with its weak
spots fixed. See **[STRATEGY.md](STRATEGY.md)** for the reasoning.

## Quick start

```bash
pip install -e '.[dev]'

# Audit one site
hala audit https://some-business.example

# Full pipeline: leads CSV -> out/campaign.csv + out/reports/*.html
export HALA_SENDER_NAME="Your Name" HALA_SENDER_COMPANY="Your Studio" \
       HALA_SENDER_EMAIL="you@studio.example" HALA_SENDER_ADDRESS="Street, City" \
       ANTHROPIC_API_KEY=...            # optional; without it a template is used
hala run examples/leads.csv --out out --report-base-url https://audits.yourstudio.com
```

Host `out/reports/` on Cloudflare Pages at the `--report-base-url`. Then import
`out/campaign.csv` into your sending tool, using a separate sending domain at a
low daily volume.

### Leads CSV columns

| column | required | used for |
|---|---|---|
| `name`, `email`, `website` | yes | identity and audit target (rows without an email are skipped) |
| `category`, `city` | no | high-ticket niche bonus, copy |
| `reviews`, `rating`, `runs_ads` | no | "can they pay" score |
| `contact_name`, `language` | no | personalization (e.g. `Filipino`) |

## What's in here

- `hala/audit.py`: homepage checks, each phrased as a business cost and ranked by impact.
- `hala/qualify.py`: opportunity × ability-to-pay scoring with A/B/C tiers. Skips sites that are already decent and leads with no email.
- `hala/report.py`: a self-contained, mobile-friendly audit page for each lead.
- `hala/pitch.py`: short emails from Claude (structured output) with a template fallback. The compliance footer is always added in code.

## Tests

```bash
pytest -q
```
