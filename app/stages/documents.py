"""Stage 6 - document checks."""
from __future__ import annotations

from datetime import date

from .. import llm
from .. import matching as m
from ..models import finding
from ..reference_data import DOC_LABELS
from ..validators import norm_id
from .completeness import doc_label

BAD_WORDS = ("electricity", "utility", "invoice", "statement of charges", "water bill", "gas bill", "telephone bill")
TAX_DOCS = ("TAX_CERTIFICATE", "W9")


def _a(label):
    return ("an " if label[:1].lower() in "aeiou" else "a ") + label


def _parse(d):
    try:
        return date.fromisoformat(str(d)[:10])
    except Exception:
        return None


def run(ctx):
    s = ctx.sub
    c, t, bk = s["company"], s["tax"], s["bank"]
    cc = c.get("country") or ""
    out = []
    for i, d in enumerate(s["documents"]):
        dt, fn, ex = d["doc_type"], d.get("filename") or f"document {i + 1}", d.get("extracted") or {}
        label = doc_label(dt, cc) if dt in DOC_LABELS else dt
        text = " ".join([fn] + [str(x) for x in ex.values()]).lower()
        bad = next((w for w in BAD_WORDS if w in text), None)
        if dt == "OTHER" or bad:
            why = ("its declared type is 'OTHER'" if dt == "OTHER" else f"it appears to be a utility bill or invoice (keyword '{bad}')")
            expected = {"TAX_CERTIFICATE": "tax registration certificate", "BANK_LETTER": "bank letter"}.get(dt, "accepted document")
            out.append(finding("DOC_TYPE_MISMATCH", "ERROR",
                               f"Attached '{fn}' as {_a(label) if dt != 'OTHER' else 'an unclassified document'}; "
                               f"this is not an accepted document - {why}.",
                               {"filename": fn, "declared_type": dt, "matched_keyword": bad, "field": "documents"},
                               (f"Replace it with the official {label}." if dt != "OTHER" else
                                "Remove it or replace it with one of the required documents.")))
            continue
        if not ex:
            out.append(finding("DOC_NOT_EXTRACTED", "INFO",
                               f"No data extracted from '{fn}'; automated content checks skipped (manual verification advised).",
                               {"filename": fn}))
            continue
        name = ex.get("name_on_document")
        if dt == "BANK_LETTER":
            if name and bk.get("account_holder"):
                sim = round(m.similarity(name, bk["account_holder"]), 3)
                if sim < 0.85:
                    out.append(finding("DOC_BANK_LETTER_HOLDER", "WARN",
                                       f"Bank letter names '{name}' but the submitted account holder is '{bk['account_holder']}'.",
                                       {"filename": fn, "name_on_document": name, "account_holder": bk["account_holder"], "similarity": sim}))
                else:
                    ctx.ok(f"Bank letter holder matches account holder ({sim:.2f})")
            issued = _parse(ex.get("issue_date"))
            if issued and (date.today() - issued).days > 365:
                out.append(finding("DOC_STALE", "WARN",
                                   f"Bank letter '{fn}' was issued on {issued} (over 12 months ago).",
                                   {"filename": fn, "issue_date": str(issued), "age_days": (date.today() - issued).days}))
        else:
            if name and c.get("legal_name"):
                sim = round(m.similarity(name, c["legal_name"]), 3)
                if sim < 0.80:
                    out.append(finding("DOC_NAME_MISMATCH", "ERROR",
                                       f"Name on '{fn}' ('{name}') does not match the legal name '{c['legal_name']}'.",
                                       {"filename": fn, "name_on_document": name, "legal_name": c["legal_name"], "similarity": sim},
                                       f"Provide a {label} issued in the company's exact legal name."))
                else:
                    ctx.ok(f"{label}: name matches legal name ({sim:.2f})")
            if dt in TAX_DOCS and ex.get("id_number") and t.get("tax_id"):
                if norm_id(ex["id_number"]) != norm_id(t["tax_id"]):
                    out.append(finding("DOC_ID_MISMATCH", "ERROR",
                                       f"Tax ID on '{fn}' ({ex['id_number']}) differs from the submitted tax ID ({t['tax_id']}).",
                                       {"filename": fn, "document_id": ex["id_number"], "submitted_tax_id": t["tax_id"]},
                                       "Confirm the correct tax ID and send a matching certificate."))
                else:
                    ctx.ok(f"{label}: tax ID matches submission")

    if llm.available():
        notes = llm.review_documents(s)
        for n in notes or []:
            out.append(finding("DOC_LLM_NOTE", "INFO", f"{n['filename']}: {n['note']}", {"source": "llm"}))
    return out
