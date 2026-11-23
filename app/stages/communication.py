"""Stage 8 - draft emails. Deterministic templates; optionally polished by the LLM."""
from __future__ import annotations

import json

from .. import llm
from ..models import finding

PROCUREMENT = "procurement-review@vendorguard.example"
COMPLIANCE = "compliance@vendorguard.example"
SIGN = "Kind regards,\nVendor Onboarding Team"


def _lines(items):
    return "\n".join(f"- [{i['severity']}] {i['rule_id']}: {i['sentence']}" for i in items)


def _evidence(ev):
    return ", ".join(f"{k}={v}" for k, v in ev.items() if v not in (None, "", [])) if ev else ""


def build_drafts(ctx) -> list[dict]:
    d, s = ctx.decision, ctx.sub
    name = (s["company"]["legal_name"] if s else None) or "your company"
    to = (s["contact"]["email"] if s else None) or "(no contact email provided)"
    greet = f"Dear {s['contact']['name']}," if s and s["contact"].get("name") else "Hello,"
    dt, rid = d["decision_type"], ctx.run_id
    out = []

    if dt.startswith("approved"):
        notes = ""
        if dt == "approved_with_notes":
            notes = "\n\nFor your information, our review noted one minor point that required no action from you."
        out.append({"audience": "vendor", "kind": "approved", "to": to,
                    "subject": f"Welcome aboard - {name} is approved as a vendor",
                    "body": f"{greet}\n\nThank you for completing our vendor onboarding. We're pleased to confirm that "
                            f"{name} has been approved. Your details have been recorded and you will be set up for "
                            f"purchase orders and payments shortly.{notes}\n\nReference: {rid}\n\n{SIGN}"})
    elif dt == "needs_vendor_action":
        errs = [f for f in ctx.findings if f["severity"] == "ERROR"]
        items = []
        for n, f in enumerate(errs, 1):
            items.append(f"{n}. {f['message']}\n   What we need: {f.get('action') or 'Please review and correct this item.'}")
        out.append({"audience": "vendor", "kind": "needs_vendor_action", "to": to,
                    "subject": f"Action needed to complete onboarding for {name}",
                    "body": f"{greet}\n\nThank you for submitting {name} for vendor onboarding. Before we can proceed, "
                            f"we need your help with the following {len(errs)} item(s):\n\n" + "\n\n".join(items) +
                            f"\n\nPlease reply to this email or resubmit via the portal with the corrections, quoting "
                            f"reference {rid}. We will re-review as soon as we hear from you.\n\n{SIGN}"})
    elif dt == "needs_human_review":
        warns = [r for r in d["reasoning"] if r["severity"] in ("WARN", "ERROR")]
        out.append({"audience": "internal", "kind": "human_review", "to": PROCUREMENT,
                    "subject": f"[Review needed] {name} - {len(warns)} combined risk signals (run {rid})",
                    "body": f"Procurement reviewer,\n\nThe vendor submission for {name} passed all hard checks (no errors or "
                            f"critical findings) but raised {len(warns)} soft risk signals that, taken together, exceed the "
                            f"auto-approval limit (1):\n\n" +
                            "\n".join(f"- {r['rule_id']}: {r['sentence']}" + (f"\n    evidence: {_evidence(r['evidence'])}" if r['evidence'] else "")
                                      for r in warns) +
                            f"\n\nSuggested checks: confirm the vendor's identity by phone using an independently sourced number, "
                            f"verify the company registration, and approve or reject in the review queue.\n\nRun: {rid}"})
        out.append({"audience": "vendor", "kind": "holding", "to": to,
                    "subject": f"Your onboarding for {name} is under review",
                    "body": f"{greet}\n\nThank you for your submission for {name}. It is now with our procurement team for "
                            f"a final review. No action is required from you at this time; we will be in touch once the "
                            f"review is complete.\n\nReference: {rid}\n\n{SIGN}"})
    else:  # rejected
        crit = [r for r in d["reasoning"] if r["severity"] == "CRITICAL"]
        out.append({"audience": "vendor", "kind": "rejected", "to": to,
                    "subject": f"Update on your vendor onboarding request - {name}",
                    "body": f"{greet}\n\nThank you for your interest in becoming a vendor and for the information you provided. "
                            f"After reviewing the submission for {name}, we are unable to proceed with onboarding at this "
                            f"time. This outcome is based on our internal vendor eligibility requirements, and we are not "
                            f"able to share further details.\n\nIf you believe this is a mistake, please contact our "
                            f"procurement team and quote reference {rid}.\n\n{SIGN}"})
        out.append({"audience": "internal", "kind": "compliance_alert", "to": COMPLIANCE,
                    "subject": f"[COMPLIANCE ALERT] Vendor submission rejected - {name} (run {rid})",
                    "body": f"Compliance team,\n\nRun {rid} for '{name}' was automatically REJECTED on "
                            f"{len(crit)} critical finding(s):\n\n" +
                            "\n".join(f"- {r['rule_id']}: {r['sentence']}\n    evidence: {_evidence(r['evidence'])}" for r in crit) +
                            f"\n\nAll findings:\n{_lines([{'severity': r['severity'], 'rule_id': r['rule_id'], 'sentence': r['sentence']} for r in d['reasoning']])}"
                            f"\n\nRecommended: do not onboard or pay this vendor; verify the details with the existing "
                            f"vendor owner where a duplicate is involved; log for audit. The vendor-facing message is "
                            f"intentionally neutral and does not mention these findings."})
    return out


def run(ctx):
    out = []
    for dft in build_drafts(ctx):
        source = "template"
        polished = llm.draft_email({"audience": dft["audience"], "kind": dft["kind"],
                                    "vendor": (ctx.sub or {}).get("company", {}).get("legal_name"),
                                    "draft": {"subject": dft["subject"], "body": dft["body"]}}) if llm.available() else None
        if polished:
            dft["subject"], dft["body"], source = polished["subject"], polished["body"], "ai"
        dft["source"] = source
        ctx.emails.append(dft)
        out.append(dft)
    ctx.ok(f"{len(out)} draft message(s) prepared (not sent)")
    return [finding("EMAIL_DRAFTED", "INFO", f"{len(out)} draft message(s) prepared (not sent).",
                    {"audiences": [e["audience"] for e in out], "source": [e["source"] for e in out]})]
