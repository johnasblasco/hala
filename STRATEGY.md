# Hala — strategy: fix the weak spots, don't copy the playbook

The "200 websites in 12 months" playbook is: scrape thousands of businesses →
auto-audit their sites → send personalized cold email about the problems →
AI-generated SEO blog for inbound → build sites with AI → host on Cloudflare.

It works, but it has weak spots. Most of the gain comes from fixing them,
not from doing the same thing at higher volume.

## The weak spots and what we do instead

| # | Weak spot in the original | Why it hurts | What Hala does |
|---|---|---|---|
| 1 | **Volume-first targeting.** "Scrape thousands," email anyone with a bad site. | A bad website alone isn't a buying signal. Many of those owners have no budget and no pain. Low reply rates mean more volume, which burns sending domains. | **Qualify before contacting** (`hala/qualify.py`). Score = *site opportunity × business can pay*: review count, rating, high-ticket category, whether they already pay for ads. Contact the top 10–20% only. |
| 2 | **Telling, not showing.** The email lists problems ("slow, not mobile friendly"). | Everyone gets "your site has issues" emails. Criticism puts owners on the defensive. | **Show the result.** Each lead gets a one-page visual audit (`hala/report.py`) in plain business language ("customers on phones can't tap your number"). Next step: a mocked-up homepage for the top replies. |
| 3 | **Technical findings, not money findings.** Weak SEO, slow load times, layout problems. | Owners don't buy "SEO." They buy calls, bookings and walk-ins. | Every check maps to a **business impact** and is ranked by it. A missing click-to-call link on a plumber's site outranks a missing meta description. |
| 4 | **One-time project revenue.** 200 sites sold one at a time. | Every month starts at zero. The pipeline has to run at full speed forever. | **Recurring care plan** in every offer: hosting, updates, monthly edits, Google Business Profile upkeep, and a monthly report. 200 sites × a small monthly fee becomes the real business. |
| 5 | **Mass AI SEO blogging.** | Google's scaled-content policies target exactly this. One core update can wipe it out. It also brings inbound from *other people's* search terms, not the clients'. | Put SEO effort where it converts: **local SEO for clients** (Google Business Profile, local schema, service-area pages built from real data) as part of the care plan. Your own content is case studies with real before/after numbers. |
| 6 | **Compliance ignored.** Scraped lists plus automated cold email. | CAN-SPAM, GDPR/PECR and the Philippine Data Privacy Act all apply. Spam complaints also destroy deliverability. | The pitch generator always includes sender identity and an opt-out line. It writes plain text with no tracking pixels and no fake "Re:" subjects. The pipeline is meant to run from a **separate sending domain** at low daily volume. Business contact data only. |
| 7 | **Paying for SaaS for every step.** Apollo + Swokei + Soro. | Costs grow with volume. The core differentiator, the analysis, isn't yours. | **Own the analysis and copy pipeline** (this repo). Pay only for lead data and email sending. |
| 8 | **AI-built sites shipped fast.** | Speed without QA means broken forms, poor accessibility and slow pages. Those turn into refunds and bad reviews. | **Run the same auditor on our own deliverables** before handoff (`hala audit <staging-url>`). A site we ship must score 90+ on our own checklist. |
| 9 | **No feedback loop.** | You can't improve what you don't measure. | `campaign.csv` keeps the score, the top issue and the pitch angle for every lead, so you can see which angles and niches actually get replies, and focus there. |

## Pipeline

```
leads.csv ─► audit (per site) ─► qualify (score + filter) ─► report.html per lead
                                                         └─► pitch (Claude) ─► campaign.csv
```

- `hala audit <url>`: audits one site and prints its findings.
- `hala run leads.csv --out out/`: runs the full pipeline. It writes `out/campaign.csv` (import into your sender) and `out/reports/<slug>.html` (host on Cloudflare Pages and link it from the email).

## Offer structure (suggested)

1. **Free:** the audit page, already done, no call needed to see it.
2. **Build:** a fixed-price site with a defined scope, priced by niche.
3. **Care plan (where the money is):** a monthly fee covering hosting, edits, GBP posts and a monthly performance report. Sell it at signing, not afterward.

## Weekly operating rhythm

- Mon: pull 300–500 leads in **2–3 high-ticket niches** (dental, legal, home services, clinics, real estate).
- Mon: `hala run`, then review the top 50 by hand (five minutes each, max).
- Tue–Thu: send 20–40/day per sending inbox, and reply within the hour.
- Fri: compare reply rate by niche and by angle. Drop the worst niche and add a new one.
