# Hala

A small, self-owned pipeline for selling websites to local businesses. It
audits each site, qualifies the lead, builds a visual report page, and writes
outreach copy.

It's modelled on the "sold 200 websites in 12 months" playbook, with its weak
spots fixed. See **[STRATEGY.md](STRATEGY.md)** for the reasoning.

## The web app (easiest)

```bash
pip install -e .
hala serve
```

Your browser opens at http://localhost:8000. From there you can:

- **Find leads**: pick a business type and towns, then click *Find leads*. Hala searches, finds emails, audits websites and writes the outreach.
- **Leads**: work through them best-first. Open one to see its audit, edit and copy the email (or open it straight in Gmail), and track its status: New → Contacted → Replied → Meeting → Won/Lost.
- **Dashboard**: shows your pipeline and which pitch angles get replies.
- **Quick audit**: check any single website.
- **Settings**: your sender details, the public report URL, and optional Google and Anthropic keys.

Your data lives in `~/.hala/hala.db` (on Windows, `C:\Users\<you>\.hala\hala.db`).

### Putting it online

To use Hala from anywhere, with a login and your data in Supabase, see
**[DEPLOY.md](DEPLOY.md)** (Vercel + Supabase).

### Changing the web app

The built UI is committed in `hala/static/`, so you don't need Node.js just to
run it. To change it:

```bash
cd web
npm install
npm run dev      # http://localhost:5173, live reload (keep `hala serve` running too)
npm run build    # writes the production build into hala/static/
```

## Command line

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

## Finding leads automatically

`hala find` searches for businesses, then visits each business's website
(homepage, then /contact and /about) to find a public email address.

```bash
# Free: OpenStreetMap, no account or key needed (the default)
hala find "dentist in Quezon City" "dentist in Makati" --out leads.csv

# or find + run the whole pipeline in one go
hala find "dentist in Quezon City" --run --no-ai
```

Write each search as `<business type> in <place>`. Known types include
dentist, clinic, vet, restaurant, cafe, salon, spa, gym, hotel, resort,
lawyer, accountant, real estate, plumber, electrician, contractor, auto repair
and school. Any other word is matched against business names.

You get two files:

- `leads.csv`: businesses that have a website, with emails filled in where one was found. This file feeds `hala run`.
- `leads-no-website.csv`: businesses with **no website at all**, with their phone number and map link. These need a site the most, so call or message them.

### Sources

| | OpenStreetMap (default) | Google Places (`--source google`) |
|---|---|---|
| Cost | Free, no key | Needs a Google Cloud key and billing (free monthly allowance) |
| Coverage | Good in big cities, patchier elsewhere | Best |
| Reviews / rating | No (ranking uses site quality and niche only) | Yes |

OpenStreetMap data © OpenStreetMap contributors (ODbL). If Google
`GOOGLE_MAPS_API_KEY` is set, `hala find` uses Google automatically.

To set up Google: at https://console.cloud.google.com/, create a project, add
billing, enable **Places API (New)**, then create an API key under
**Credentials**. Each Google search returns at most 60 businesses, so run
several searches (one per city or barangay).

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
