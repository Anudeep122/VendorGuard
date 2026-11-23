"""Stage 3 - identifier format validation with real algorithms."""
from __future__ import annotations

from datetime import date

from .. import validators as v
from ..models import finding
from ..reference_data import COUNTRY_NAMES

EXPECT = {
    "IN": "a 15-character GSTIN (e.g. 27AAPFU0939F1ZV)",
    "US": "a US EIN (format NN-NNNNNNN, e.g. 12-3456789)",
    "GB": "a UK VAT number (GB + 9 digits)",
    "DE": "a German VAT number (DE + 9 digits)",
    "AE": "a UAE TRN (15 digits)",
}


def run(ctx):
    s = ctx.sub
    c, t, bk, ct = s["company"], s["tax"], s["bank"], s["contact"]
    cc = c.get("country")
    out = []

    # ---- tax id vs claimed country
    tid = t.get("tax_id")
    if tid and cc:
        if v.shape_matches(cc, tid):
            if cc == "IN":
                err = v.check_gstin(tid)
                if err:
                    out.append(finding("FORMAT_GSTIN", "ERROR", f"GSTIN '{tid}' is invalid: {err}.",
                                       {"field": "tax.tax_id", "value": tid},
                                       "Provide the correct 15-character GSTIN exactly as on your GST registration certificate."))
                else:
                    ctx.ok(f"GSTIN {tid} valid (pattern, state code, checksum)")
            else:
                ctx.ok(f"Tax ID {tid} matches {v.TAXID_LABELS[cc]} format")
        else:
            others = [x for x in v.detect_taxid_countries(tid) if x != cc]
            if others:
                o = others[0]
                out.append(finding(
                    "FORMAT_TAXID_COUNTRY", "ERROR",
                    f"Tax ID '{tid}' matches the {v.TAXID_LABELS[o]} format ({COUNTRY_NAMES[o]}), but the company is "
                    f"registered in {COUNTRY_NAMES[cc]}.",
                    {"field": "tax.tax_id", "value": tid, "claimed_country": cc, "detected_country": o,
                     "expected_format": v.TAXID_EXAMPLES[cc]},
                    f"Provide {EXPECT[cc]}" + (" and a completed IRS Form W-9." if cc == "US" else
                                                 ", or correct the country of registration if it is wrong.")))
            else:
                rule = "FORMAT_GSTIN" if cc == "IN" else "FORMAT_TAXID"
                out.append(finding(rule, "ERROR",
                                   f"Tax ID '{tid}' does not match the expected format for {COUNTRY_NAMES[cc]} "
                                   f"({v.TAXID_EXAMPLES[cc]}).",
                                   {"field": "tax.tax_id", "value": tid, "expected_format": v.TAXID_EXAMPLES[cc]},
                                   f"Provide {EXPECT[cc]}."))

    # ---- PAN / IFSC
    if t.get("pan"):
        e = v.check_pan(t["pan"])
        if e:
            out.append(finding("FORMAT_PAN", "ERROR", f"PAN '{t['pan']}' is invalid: {e}.",
                               {"field": "tax.pan", "value": t["pan"]}, "Provide the correct 10-character PAN."))
        else:
            ctx.ok(f"PAN {t['pan']} valid")
    if bk.get("ifsc"):
        e = v.check_ifsc(bk["ifsc"])
        if e:
            out.append(finding("FORMAT_IFSC", "ERROR", f"IFSC '{bk['ifsc']}' is invalid: {e}.",
                               {"field": "bank.ifsc", "value": bk["ifsc"]}, "Provide the correct 11-character IFSC of the branch."))
        else:
            ctx.ok(f"IFSC {bk['ifsc']} valid")

    # ---- IBAN / BIC
    if bk.get("iban"):
        e = v.check_iban(bk["iban"])
        if e:
            out.append(finding("FORMAT_IBAN", "ERROR", f"IBAN '{bk['iban']}' is invalid: {e}.",
                               {"field": "bank.iban", "value": bk["iban"]},
                               "Provide the correct IBAN exactly as printed on your bank statement or letter."))
        else:
            ctx.ok("IBAN valid (length + mod-97 checksum)")
    if bk.get("swift_bic"):
        e = v.check_bic(bk["swift_bic"])
        if e:
            out.append(finding("FORMAT_SWIFT", "ERROR", f"SWIFT/BIC '{bk['swift_bic']}' is invalid: {e}.",
                               {"field": "bank.swift_bic", "value": bk["swift_bic"]}, "Provide the correct 8 or 11 character SWIFT/BIC."))
        else:
            ctx.ok(f"SWIFT/BIC {bk['swift_bic']} valid")

    # ---- US routing
    if bk.get("routing_number"):
        e = v.check_aba(bk["routing_number"])
        if e:
            out.append(finding("FORMAT_ROUTING", "ERROR", f"Routing number '{bk['routing_number']}' is invalid: {e}.",
                               {"field": "bank.routing_number", "value": bk["routing_number"]},
                               "Provide the correct 9-digit ABA routing number."))
        else:
            ctx.ok("ABA routing number valid (checksum)")

    # ---- contact
    if ct.get("email"):
        e = v.check_email(ct["email"])
        if e:
            out.append(finding("FORMAT_EMAIL", "ERROR", f"Contact email '{ct['email']}' is invalid: {e}.",
                               {"field": "contact.email", "value": ct["email"]}, "Provide a valid business email address."))
        else:
            ctx.ok("Email syntax valid")
    if ct.get("phone"):
        e = v.check_phone(ct["phone"])
        if e:
            out.append(finding("FORMAT_PHONE", "ERROR", f"Phone '{ct['phone']}' looks invalid: {e}.",
                               {"field": "contact.phone", "value": ct["phone"]}, "Provide a reachable phone number in international format."))
        else:
            ctx.ok("Phone plausible")

    # ---- dates
    inc = c.get("incorporation_date")
    if inc and date.fromisoformat(inc) > date.today():
        out.append(finding("FORMAT_DATE", "ERROR", f"Incorporation date {inc} is in the future.",
                           {"field": "company.incorporation_date", "value": inc}, "Provide the correct date of incorporation."))
    return out
