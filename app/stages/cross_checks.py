"""Stage 4 - cross-field consistency."""
from __future__ import annotations

from .. import matching as m
from .. import validators as v
from ..models import finding
from ..reference_data import COUNTRY_NAMES, IFSC_BANKS


def run(ctx):
    s = ctx.sub
    c, t, bk = s["company"], s["tax"], s["bank"]
    cc = c.get("country")
    out = []

    # ---- account holder vs legal name
    holder, legal, trading = bk.get("account_holder"), c.get("legal_name"), c.get("trading_name")
    if holder and legal:
        sim = round(m.similarity(holder, legal), 3)
        ev = {"account_holder": holder, "legal_name": legal, "similarity": sim}
        if sim >= 0.90:
            ctx.ok(f"Account holder matches legal name (similarity {sim:.2f})")
        elif m.is_acronym_match(holder, legal):
            out.append(finding("CROSS_ACCOUNT_HOLDER_NAME", "INFO",
                               f"Account holder '{holder}' accepted: it is the acronym/initialism of '{legal}' "
                               f"({m.initials(legal).upper()}). Treated as a legitimate name variant.",
                               dict(ev, reason="acronym_match")))
        elif trading and (m.similarity(holder, trading) >= 0.90 or m.is_acronym_match(holder, trading)):
            out.append(finding("CROSS_ACCOUNT_HOLDER_NAME", "INFO",
                               f"Account holder '{holder}' accepted: it matches the declared trading name '{trading}'.",
                               dict(ev, reason="trading_name_match", trading_name=trading)))
        elif sim >= 0.70:
            out.append(finding("CROSS_ACCOUNT_HOLDER_NAME", "WARN",
                               f"Account holder '{holder}' only partially matches legal name '{legal}' (similarity {sim:.2f}).",
                               ev))
        elif m.looks_like_person(holder, legal):
            out.append(finding("CROSS_ACCOUNT_HOLDER_NAME", "CRITICAL",
                               f"Bank account is held by an individual ('{holder}'), not the company '{legal}'; "
                               "possible payment diversion.", dict(ev, reason="individual_name")))
        else:
            out.append(finding("CROSS_ACCOUNT_HOLDER_NAME", "ERROR",
                               f"Account holder '{holder}' does not match legal name '{legal}' (similarity {sim:.2f}).",
                               dict(ev, field="bank.account_holder"),
                               "Provide a bank account held in the company's legal name, or a bank letter proving the holder name is a registered name of the company."))

    # ---- countries
    if bk.get("bank_country") and cc and bk["bank_country"] != cc:
        out.append(finding("CROSS_BANK_COUNTRY", "WARN",
                           f"Bank is in {bk['bank_country']} but the company is registered in {cc}.",
                           {"bank_country": bk["bank_country"], "company_country": cc}))
    elif bk.get("bank_country") and cc:
        ctx.ok("Bank country matches company country")
    ac = c["address"].get("country")
    if ac and cc and ac != cc:
        out.append(finding("CROSS_ADDRESS_COUNTRY", "ERROR",
                           f"Address country ({ac}) differs from the company's country of registration ({cc}).",
                           {"address_country": ac, "company_country": cc, "field": "company.address.country"},
                           "Correct the registered address or the country of registration so they agree."))
    elif ac and cc:
        ctx.ok("Address country matches company country")

    # ---- GSTIN <-> PAN
    if cc == "IN" and t.get("tax_id") and t.get("pan") and v.check_gstin(t["tax_id"]) is None:
        embedded = t["tax_id"][2:12]
        if embedded != t["pan"]:
            out.append(finding("CROSS_GSTIN_PAN", "ERROR",
                               f"PAN embedded in GSTIN ({embedded}) does not match the submitted PAN ({t['pan']}).",
                               {"gstin": t["tax_id"], "gstin_pan": embedded, "pan": t["pan"], "field": "tax.pan"},
                               "Confirm and resubmit the PAN and GSTIN that belong to the same legal entity."))
        else:
            ctx.ok("PAN matches characters 3-12 of GSTIN")

    # ---- IFSC <-> bank name
    ifsc, bname = bk.get("ifsc"), (bk.get("bank_name") or "")
    if ifsc and bname and v.check_ifsc(ifsc) is None:
        exp = IFSC_BANKS.get(ifsc[:4])
        if exp:
            if exp in bname.lower():
                ctx.ok(f"IFSC prefix {ifsc[:4]} consistent with bank '{bname}'")
            else:
                out.append(finding("CROSS_IFSC_BANK", "WARN",
                                   f"IFSC prefix {ifsc[:4]} normally belongs to {exp.title()}, but bank name is '{bname}'.",
                                   {"ifsc": ifsc, "expected_bank": exp, "bank_name": bname}))

    # ---- IBAN country
    if bk.get("iban") and bk.get("bank_country"):
        if bk["iban"][:2] != bk["bank_country"]:
            out.append(finding("CROSS_IBAN_COUNTRY", "ERROR",
                               f"IBAN country prefix ({bk['iban'][:2]}) differs from the stated bank country ({bk['bank_country']}).",
                               {"iban": bk["iban"], "bank_country": bk["bank_country"], "field": "bank.bank_country"},
                               "Correct the bank country or provide the IBAN of the account you intend to be paid into."))
        else:
            ctx.ok("IBAN country matches bank country")

    # ---- postal format
    pc = c["address"].get("postal_code")
    if cc and pc:
        e = v.check_postal(cc, pc)
        if e:
            out.append(finding("CROSS_POSTAL", "WARN", e + ".", {"postal_code": pc, "country": cc}))
    return out
