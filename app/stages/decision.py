"""Stage 7 - deterministic decision. No LLM involvement."""
from __future__ import annotations

from .. import db
from ..models import SEV_SCORE, finding

TYPES = {
    "rejected_critical": ("Rejected", "Critical integrity/compliance finding - do not onboard"),
    "needs_vendor_action": ("Pending", "Fixable issues - waiting on the vendor"),
    "needs_human_review": ("Pending", "Multiple soft risk signals - escalated to a procurement reviewer"),
    "approved_clean": ("Approved", "All checks passed"),
    "approved_with_notes": ("Approved", "Approved with one soft risk note"),
}


def decide(findings: list[dict]) -> dict:
    by = lambda sev: [f for f in findings if f["severity"] == sev]
    crit, errs, warns, infos = by("CRITICAL"), by("ERROR"), by("WARN"), by("INFO")
    system_fail = any(f["evidence"].get("system") for f in errs)
    if crit:
        dtype = "rejected_critical"
        summary = (f"Rejected: {len(crit)} critical finding(s) ({', '.join(sorted({f['rule_id'] for f in crit}))}). "
                   "These indicate an integrity or compliance risk, so the vendor cannot be onboarded automatically.")
    elif system_fail:
        dtype = "needs_human_review"
        summary = "Pending human review: an automated check could not complete, so a reviewer must verify this submission."
    elif errs:
        dtype = "needs_vendor_action"
        summary = (f"Pending: {len(errs)} fixable issue(s) must be corrected by the vendor "
                   f"({', '.join(sorted({f['rule_id'] for f in errs}))}). No integrity or fraud signals were raised.")
    elif len(warns) >= 2:
        dtype = "needs_human_review"
        summary = (f"Pending human review: {len(warns)} soft risk signals ({', '.join(f['rule_id'] for f in warns)}) "
                   "were raised. Multiple soft risk signals combined; escalate to a procurement reviewer.")
    elif len(warns) == 1:
        dtype = "approved_with_notes"
        summary = f"Approved with notes: all checks passed apart from one soft signal ({warns[0]['rule_id']})."
    else:
        dtype = "approved_clean"
        summary = "Approved: all checks passed with no warnings." + (f" {len(infos)} informational note(s) recorded." if infos else "")
    status, meaning = TYPES[dtype]
    shown = [f for f in findings if f["severity"] != "INFO"]
    order = {"CRITICAL": 0, "ERROR": 1, "WARN": 2}
    shown.sort(key=lambda f: order[f["severity"]])
    score = min(100, sum(SEV_SCORE[f["severity"]] for f in findings))
    return {
        "status": status, "decision_type": dtype, "meaning": meaning, "summary": summary, "risk_score": score,
        "counts": {k: len(v) for k, v in (("CRITICAL", crit), ("ERROR", errs), ("WARN", warns), ("INFO", infos))},
        "reasoning": [{"rule_id": f["rule_id"], "severity": f["severity"], "sentence": f["message"],
                       "evidence": f["evidence"]} for f in shown],
        "notes": [{"rule_id": f["rule_id"], "sentence": f["message"], "evidence": f["evidence"]} for f in infos],
    }


def run(ctx):
    d = decide(ctx.findings)
    ctx.decision = d
    if d["status"] == "Approved" and ctx.sub:
        s = ctx.sub
        db.insert_vendor({
            "name": s["company"]["legal_name"], "country": s["company"]["country"], "tax_id": s["tax"].get("tax_id"),
            "account_number": s["bank"].get("account_number"), "iban": s["bank"].get("iban"),
            "routing": s["bank"].get("routing_number"), "ifsc": s["bank"].get("ifsc")},
            source="onboarded", run_id=ctx.run_id, created_at=ctx.started_at)
        ctx.ok("Vendor added to the approved-vendor master for future duplicate detection")
    return [finding("DECISION", "INFO", f"{d['status']} ({d['decision_type']}); risk score {d['risk_score']}/100 (informational).",
                    {"status": d["status"], "decision_type": d["decision_type"], "risk_score": d["risk_score"]})]
