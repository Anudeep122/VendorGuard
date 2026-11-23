"""Stage 5 - risk / fraud signals."""
from __future__ import annotations

import re
from datetime import date

from .. import db
from .. import matching as m
from ..models import finding
from ..reference_data import FREE_EMAIL_DOMAINS, WATCHLIST, WATCHLIST_THRESHOLD


def _domain_of_site(site: str) -> str:
    s = re.sub(r"^[a-z]+://", "", site.strip().lower())
    s = s.split("/")[0].split(":")[0]
    return s[4:] if s.startswith("www.") else s


def run(ctx):
    s = ctx.sub
    c, t, bk, ct = s["company"], s["tax"], s["bank"], s["contact"]
    out = []

    # ---- watchlist
    seen = set()
    for field, val in (("legal_name", c.get("legal_name")), ("trading_name", c.get("trading_name")),
                       ("account_holder", bk.get("account_holder"))):
        if not val:
            continue
        for entry in WATCHLIST:
            score = round(m.name_match_score(val, entry), 3)
            if score >= WATCHLIST_THRESHOLD and (entry, val.lower()) not in seen:
                seen.add((entry, val.lower()))
                out.append(finding("RISK_WATCHLIST", "CRITICAL",
                                   f"{field.replace('_', ' ').capitalize()} '{val}' matches watchlist entry "
                                   f"'{entry}' (score {score:.2f} >= {WATCHLIST_THRESHOLD}).",
                                   {"field": field, "input": val, "matched_entry": entry, "score": score,
                                    "threshold": WATCHLIST_THRESHOLD}))
    if not any(f["rule_id"] == "RISK_WATCHLIST" for f in out):
        ctx.ok(f"No watchlist match ({len(WATCHLIST)} entries screened)")

    # ---- duplicates in vendor master
    found = db.find_vendors(bk.get("account_number"), bk.get("iban"), t.get("tax_id"))
    dup_warned = False
    for r in found["bank"]:
        sim = m.similarity(c.get("legal_name"), r["name"])
        ev = {"existing_vendor": r["name"], "existing_country": r["country"], "name_similarity": round(sim, 3),
              "account": bk.get("iban") or bk.get("account_number")}
        if sim < 0.7:
            out.append(finding("RISK_DUPLICATE_BANK", "CRITICAL",
                               f"Bank account already registered to vendor '{r['name']}' - different from "
                               f"'{c.get('legal_name')}'; classic payment fraud pattern.", ev))
        elif not dup_warned:
            dup_warned = True
            out.append(finding("RISK_DUPLICATE_VENDOR", "WARN",
                               f"Bank account already registered to '{r['name']}', which has a matching name; "
                               "possible duplicate onboarding.", ev))
    for r in found["tax"]:
        sim = m.similarity(c.get("legal_name"), r["name"])
        ev = {"existing_vendor": r["name"], "tax_id": t.get("tax_id"), "name_similarity": round(sim, 3)}
        if sim < 0.7:
            out.append(finding("RISK_DUPLICATE_TAXID", "CRITICAL",
                               f"Tax ID {t.get('tax_id')} already registered to vendor '{r['name']}' under a different name.", ev))
        elif not dup_warned:
            dup_warned = True
            out.append(finding("RISK_DUPLICATE_VENDOR", "WARN",
                               f"Tax ID already registered to '{r['name']}', which has a matching name; possible duplicate onboarding.", ev))
    if not found["bank"] and not found["tax"]:
        ctx.ok("Bank account and tax ID not present in vendor master")

    # ---- email signals
    email = ct.get("email") or ""
    edom = email.split("@")[-1] if "@" in email else ""
    free = edom in FREE_EMAIL_DOMAINS
    if free:
        out.append(finding("RISK_FREE_EMAIL", "WARN", f"Contact email uses a free mail provider ({edom}).",
                           {"email_domain": edom}))
    site = c.get("website")
    if site and edom:
        sd = _domain_of_site(site)
        if not (edom == sd or edom.endswith("." + sd) or sd.endswith("." + edom)):
            out.append(finding("RISK_EMAIL_DOMAIN_MISMATCH", "WARN",
                               f"Email domain ({edom}) does not match the company website domain ({sd}).",
                               {"email_domain": edom, "website_domain": sd}))
        else:
            ctx.ok("Email domain matches website domain")

    # ---- company age
    inc = c.get("incorporation_date")
    if inc:
        days = (date.today() - date.fromisoformat(inc)).days
        if 0 <= days < 90:
            out.append(finding("RISK_NEW_COMPANY", "WARN", f"Company was incorporated only {days} days ago (< 90 days).",
                               {"incorporation_date": inc, "days_since_incorporation": days}))
        elif days >= 90:
            ctx.ok(f"Company age {days // 365}y {days % 365 // 30}m (>= 90 days)")

    # ---- web presence
    if not site:
        if free:
            out.append(finding("RISK_NO_WEBSITE", "WARN",
                               "No website provided and contact email is on a free provider: no verifiable online presence.",
                               {"website": None, "email_domain": edom, "escalated_from": "INFO"}))
        else:
            out.append(finding("RISK_NO_WEBSITE", "INFO", "No website provided (corporate email domain present).",
                               {"website": None}))
    return out
