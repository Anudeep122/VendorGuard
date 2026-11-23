"""Stage 2 - country-specific required fields and documents."""
from __future__ import annotations

from ..models import finding
from ..reference_data import COUNTRY_NAMES, DOC_ACTIONS, DOC_LABELS, REQUIRED_DOCS

FIELD_HELP = {
    "company.legal_name": ("legal company name", "Provide the full legal name exactly as registered."),
    "company.country": ("country of registration", "State the country where the company is registered (IN, US, GB, DE or AE)."),
    "company.address.line1": ("registered address (line 1)", "Provide the registered street address."),
    "company.address.city": ("address city", "Provide the city of the registered address."),
    "company.address.postal_code": ("address postal code", "Provide the postal/ZIP code of the registered address."),
    "contact.email": ("contact email", "Provide a monitored business email address for onboarding communication."),
    "bank.account_holder": ("bank account holder name", "Provide the account holder name exactly as it appears at the bank."),
    "bank.bank_country": ("bank country", "State the country where the bank account is held."),
    "tax.tax_id": ("tax ID", "Provide your tax registration number."),
    "tax.pan": ("PAN", "Provide the company's 10-character PAN (e.g. ABCDE1234F)."),
    "bank.account_number": ("bank account number", "Provide the bank account number."),
    "bank.ifsc": ("bank IFSC code", "Provide the branch IFSC code (e.g. HDFC0001234)."),
    "bank.routing_number": ("bank routing (ABA) number", "Provide the 9-digit ABA routing number of the bank."),
    "bank.iban": ("IBAN", "Provide the full IBAN of the receiving account."),
    "bank.swift_bic": ("SWIFT/BIC code", "Provide the SWIFT/BIC code of the receiving bank (8 or 11 characters) - needed to route international payments."),
}
TAXID_NAME = {"IN": "GSTIN", "US": "EIN", "GB": "VAT number (GB + 9 digits)", "DE": "VAT number (DE + 9 digits)",
              "AE": "TRN (15 digits)"}


def _get(sub, path):
    cur = sub
    for p in path.split("."):
        cur = cur.get(p) if isinstance(cur, dict) else None
    return cur


def doc_label(doc_type: str, country: str) -> str:
    lab = DOC_LABELS.get(doc_type, doc_type)
    return lab.get(country, "tax registration certificate") if isinstance(lab, dict) else lab


def run(ctx):
    s = ctx.sub
    cc = s["company"].get("country")
    required = ["company.legal_name", "company.country", "company.address.line1", "company.address.city",
                "company.address.postal_code", "contact.email", "bank.account_holder", "bank.bank_country"]
    any_of = []  # (paths, label)
    if cc == "IN":
        required += ["tax.tax_id", "tax.pan", "bank.account_number", "bank.ifsc"]
    elif cc == "US":
        required += ["tax.tax_id", "bank.account_number", "bank.routing_number"]
    elif cc == "GB":
        required += ["tax.tax_id", "bank.swift_bic"]
        any_of.append((["bank.account_number", "bank.iban"], "bank account number or IBAN"))
    elif cc == "DE":
        required += ["tax.tax_id", "bank.iban", "bank.swift_bic"]
    elif cc == "AE":
        required += ["tax.tax_id", "bank.iban", "bank.swift_bic"]

    out = []
    for path in required:
        if not _get(s, path):
            label, how = FIELD_HELP[path]
            if path == "tax.tax_id" and cc:
                label = TAXID_NAME[cc]
            out.append(finding("COMPLETENESS_MISSING_FIELD", "ERROR",
                               f"Missing required field: {label} ({path}).",
                               {"field": path, "country": cc}, how))
    for paths, label in any_of:
        if not any(_get(s, p) for p in paths):
            out.append(finding("COMPLETENESS_MISSING_FIELD", "ERROR", f"Missing required field: {label} ({' or '.join(paths)}).",
                               {"field": paths[0], "country": cc},
                               f"Provide the {label} of the receiving account."))
    if cc is None:
        ctx.ok("Country-specific rules skipped (country missing)")
        return out

    have = {d["doc_type"] for d in s["documents"]}
    for dt in REQUIRED_DOCS[cc]:
        if dt not in have:
            lab = doc_label(dt, cc)
            out.append(finding("COMPLETENESS_MISSING_DOC", "ERROR",
                               f"Required document missing: {lab}.",
                               {"doc_type": dt, "country": cc},
                               DOC_ACTIONS[dt].format(label=lab)))
    if not out:
        ctx.ok(f"All required fields present for {COUNTRY_NAMES[cc]}")
        ctx.ok("All required documents attached: " + ", ".join(REQUIRED_DOCS[cc]))
    return out
