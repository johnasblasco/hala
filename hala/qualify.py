"""Lead qualification: contact the businesses that need a site *and* can pay for one.

A bad website on its own is not a buying signal. We weigh the site's opportunity
(how much room for improvement) against signals that the business has revenue
worth protecting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .audit import AuditResult

# Niches where one new customer is worth a lot, so a site pays for itself fast.
HIGH_TICKET = {
    "dentist", "dental", "clinic", "medical", "dermatology", "law", "lawyer", "attorney",
    "legal", "real estate", "realtor", "plumber", "plumbing", "electrician", "hvac",
    "roofing", "contractor", "construction", "solar", "auto repair", "veterinary", "vet",
    "accounting", "accountant", "insurance", "wedding", "aesthetic", "spa", "orthodontist",
}


@dataclass
class Qualification:
    score: int          # 0-100, higher = contact first
    tier: str           # A / B / C / skip
    opportunity: int    # 0-100, from the audit
    ability: int        # 0-100, can they pay
    reasons: list[str]


def _num(v, default=0.0) -> float:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _truthy(v) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "y"}


def qualify(lead: dict, audit: AuditResult) -> Qualification:
    reasons: list[str] = []

    if not (lead.get("email") or "").strip():
        return Qualification(0, "skip", 0, 0, ["no contact email"])

    opportunity = 100 - audit.score
    if not audit.reachable:
        reasons.append("site is down")
    elif audit.top_finding:
        reasons.append(f"top issue: {audit.top_finding.id}")

    ability = 0.0
    reviews = _num(lead.get("reviews"))
    if reviews:
        # About 40 points at 100 reviews, levelling off around 1000.
        ability += min(45.0, 20 * math.log10(reviews + 1))
        reasons.append(f"{int(reviews)} reviews")
    rating = _num(lead.get("rating"))
    if rating >= 4.3:
        ability += 15
        reasons.append(f"rating {rating}")
    category = (lead.get("category") or "").lower()
    if any(k in category for k in HIGH_TICKET):
        ability += 25
        reasons.append("high-ticket niche")
    if _truthy(lead.get("runs_ads")):
        # Already paying for traffic that lands on a bad site: the strongest signal.
        ability += 25
        reasons.append("already paying for ads")
    ability = min(100.0, ability)

    score = round(0.55 * opportunity + 0.45 * ability)
    if opportunity < 20:
        tier = "skip"
        reasons.append("site is already decent")
    elif score >= 60:
        tier = "A"
    elif score >= 45:
        tier = "B"
    else:
        tier = "C"
    return Qualification(score, tier, opportunity, round(ability), reasons)
