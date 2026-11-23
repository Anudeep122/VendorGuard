"""Sample scenarios, historical-run seeding and startup initialisation.

All identifiers are generated programmatically so every GSTIN checksum, IBAN mod-97 and ABA
checksum is genuinely valid. Dates are computed relative to today.
"""
from __future__ import annotations

import copy
import json
import os
import random
import string
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import db, reference_data as ref
from .validators import make_aba, make_gstin, make_iban

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "samples"


def _d(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _deep_update(base: dict, upd: dict) -> dict:
    for k, v in upd.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v
    return base


ADDR = {
    "IN": ("Plot 12, MIDC Industrial Area", "Pune", "411019", "+919812345678", "HDFC Bank"),
    "US": ("250 Market Street", "Austin", "78701", "+15125550142", "JPMorgan Chase"),
    "GB": ("14 Clerkenwell Road", "London", "EC1M 5PQ", "+442071234567", "NatWest"),
    "DE": ("Industriestrasse 8", "Stuttgart", "70565", "+4971112345678", "Commerzbank"),
    "AE": ("Unit 204, Jebel Ali Free Zone", "Dubai", "PO Box 51234", "+97141234567", "Emirates NBD"),
}


def make_sub(country: str, name: str, domain: str | None, seed: int, *, holder: str | None = None,
             inc_days: int = 2200, **over) -> dict:
    """A fully valid, clean submission for `country`. `over` is deep-merged on top."""
    r = random.Random(seed)
    L = lambda n: "".join(r.choice(string.ascii_uppercase) for _ in range(n))
    D = lambda n: "".join(r.choice(string.digits) for _ in range(n))
    line1, city, postal, phone, bank_name = ADDR[country]
    holder = holder or name
    tax: dict = {}
    bank: dict = {"bank_name": bank_name, "account_holder": holder, "bank_country": country}
    if country == "IN":
        pan = L(3) + "C" + L(1) + D(4) + L(1)
        tid = make_gstin("27", pan)
        tax = {"tax_id": tid, "tax_id_type": "GSTIN", "pan": pan}
        bank.update(account_number="6" + D(11), ifsc="HDFC000" + D(4))
        acct_ref = bank["account_number"]
    elif country == "US":
        tid = f"{r.randrange(10, 99)}-{D(7)}"
        tax = {"tax_id": tid, "tax_id_type": "EIN"}
        bank.update(account_number="7" + D(9), routing_number=make_aba("02100002"))
        acct_ref = bank["account_number"]
    elif country == "GB":
        tid = "GB" + D(9)
        tax = {"tax_id": tid, "tax_id_type": "VAT"}
        bank.update(iban=make_iban("GB", "NWBK" + "601613" + D(8)), swift_bic="NWBKGB2L")
        acct_ref = bank["iban"]
    elif country == "DE":
        tid = "DE" + D(9)
        tax = {"tax_id": tid, "tax_id_type": "VAT"}
        bank.update(iban=make_iban("DE", "37040044" + D(10)), swift_bic="COBADEFF")
        acct_ref = bank["iban"]
    else:  # AE
        tid = "100" + D(12)
        tax = {"tax_id": tid, "tax_id_type": "VAT"}
        bank.update(iban=make_iban("AE", "033" + D(16)), swift_bic="EBILAEAD")
        acct_ref = bank["iban"]
    cert = "W9" if country == "US" else "TAX_CERTIFICATE"
    sub = {
        "company": {
            "legal_name": name, "trading_name": None, "country": country,
            "registration_number": "REG-" + D(8), "incorporation_date": _d(inc_days),
            "address": {"line1": line1, "city": city, "postal_code": postal, "country": country},
            "website": f"www.{domain}" if domain else None,
        },
        "tax": tax,
        "contact": {"name": "Accounts Payable", "email": f"accounts@{domain}" if domain else "accounts@example.invalid",
                    "phone": phone},
        "bank": bank,
        "documents": [
            {"doc_type": cert, "filename": {"W9": "form_w9_signed.pdf"}.get(cert, "tax_registration_certificate.pdf"),
             "extracted": {"name_on_document": name, "id_number": tid, "issue_date": _d(inc_days - 20 if inc_days > 40 else 5)}},
            {"doc_type": "BANK_LETTER", "filename": "bank_letter.pdf",
             "extracted": {"name_on_document": holder, "id_number": acct_ref, "issue_date": _d(30)}},
        ],
    }
    return _deep_update(sub, copy.deepcopy(over))


def build_samples() -> dict[str, dict]:
    """key -> {title, description, tests, expected:{status, decision_type}, submission, [parent_sample]}"""
    S: dict[str, dict] = {}

    # 1. happy path
    s1 = make_sub("IN", "Meridian Precision Components Pvt Ltd", "meridianprecision.in", 101,
                  holder="Meridian Precision Components Private Limited", inc_days=6 * 365,
                  bank={"ifsc": "HDFC0004321", "bank_name": "HDFC Bank"})
    S["1_clean"] = dict(
        title="Clean submission", tests="Happy path",
        description="Indian vendor with valid GSTIN/PAN pair, matching documents, corporate email on its own domain. "
                    "Account holder uses 'Private Limited' vs 'Pvt Ltd' - the suffix variant must still pass.",
        expected={"status": "Approved", "decision_type": "approved_clean"}, submission=s1)

    # 2. legitimate name variant
    s2 = make_sub("IN", "Northwind Logistics Solutions Pvt Ltd", "northwindlogistics.in", 102,
                  holder="NLS Pvt Ltd", inc_days=1500,
                  bank={"ifsc": "ICIC0002345", "bank_name": "ICICI Bank"},
                  contact={"email": "accounts@nlspl.in"})
    s2["documents"][1]["extracted"]["name_on_document"] = "NLS Pvt Ltd"
    S["2_name_variant"] = dict(
        title="Legitimate name variant", tests="Not naively strict",
        description="Account holder 'NLS Pvt Ltd' is the initialism of 'Northwind Logistics Solutions'. Accepted with an "
                    "INFO note. One benign WARN (email domain differs from website domain) yields 'approved with notes'.",
        expected={"status": "Approved", "decision_type": "approved_with_notes"}, submission=s2)

    # 3. incomplete + wrong document
    s3 = make_sub("GB", "Harlow & Finch Consulting Ltd", "harlowfinch.co.uk", 103, inc_days=1200,
                  bank={"iban": "GB82WEST12345698765432", "bank_name": "NatWest"})
    del s3["bank"]["swift_bic"]
    s3["company"]["address"]["postal_code"] = "EC2A 4NE"
    s3["documents"] = [{"doc_type": "TAX_CERTIFICATE", "filename": "electricity_bill_oct.pdf",
                        "extracted": {"name_on_document": "Harlow & Finch Consulting Ltd", "id_number": "",
                                      "issue_date": _d(40), "document_title": "Electricity bill - statement of charges"}}]
    S["3_incomplete_wrong_doc"] = dict(
        title="Incomplete + wrong document", tests="Vendor-fixable errors, email checklist, resubmission loop",
        description="UK vendor: SWIFT/BIC missing, the 'tax certificate' is actually an electricity bill, and the bank "
                    "letter is missing. The vendor email must list all three items. Then run sample 3b to resubmit.",
        expected={"status": "Pending", "decision_type": "needs_vendor_action"}, submission=s3)

    s3b = copy.deepcopy(s3)
    s3b["bank"]["swift_bic"] = "NWBKGB2L"
    s3b["documents"] = [
        {"doc_type": "TAX_CERTIFICATE", "filename": "vat_registration_certificate.pdf",
         "extracted": {"name_on_document": "Harlow & Finch Consulting Ltd", "id_number": s3["tax"]["tax_id"], "issue_date": _d(700)}},
        {"doc_type": "BANK_LETTER", "filename": "natwest_bank_letter.pdf",
         "extracted": {"name_on_document": "Harlow & Finch Consulting Ltd", "id_number": "GB82WEST12345698765432", "issue_date": _d(18)}}]
    S["3b_resubmission"] = dict(
        title="Resubmission of sample 3", tests="Resubmission loop",
        description="The corrected version of sample 3 (SWIFT added, real VAT certificate, bank letter attached). Linked to "
                    "the parent run; the run view shows which issues were resolved.",
        expected={"status": "Approved", "decision_type": "approved_clean"}, submission=s3b,
        parent_sample="3_incomplete_wrong_doc")

    # 4. individual's name
    s4 = make_sub("DE", "Brightwave Analytics GmbH", "brightwave-analytics.de", 104, holder="Markus Vogel", inc_days=900,
                  bank={"iban": make_iban("DE", "370400440532013001")})
    s4["documents"][1]["extracted"].update(id_number=s4["bank"]["iban"])
    S["4_individual_account"] = dict(
        title="Individual's name on a corporate account", tests="Payment-diversion cross-check (CRITICAL)",
        description="Every identifier is valid, so the form looks fine - only comparing the account holder 'Markus Vogel' "
                    "with the company name catches it. Vendor email is neutral; compliance gets the detail.",
        expected={"status": "Rejected", "decision_type": "rejected_critical"}, submission=s4)

    # 5. duplicate bank account
    s5 = make_sub("US", "Zenith Office Supplies LLC", "zenithoffice.com", 105, inc_days=1100,
                  tax={"tax_id": "52-7654321"},
                  bank={"account_number": ref.CASCADE_ACCOUNT, "routing_number": ref.CASCADE_ROUTING, "bank_name": "JPMorgan Chase"})
    s5["documents"][0]["extracted"]["id_number"] = "52-7654321"
    s5["documents"][1]["extracted"]["id_number"] = ref.CASCADE_ACCOUNT
    S["5_duplicate_bank"] = dict(
        title="Bank account already registered to another vendor", tests="Duplicate-account fraud pattern (CRITICAL)",
        description="All formats valid, but the bank account is identical to existing vendor Cascade Industrial Supply LLC. "
                    "The evidence names the existing vendor.",
        expected={"status": "Rejected", "decision_type": "rejected_critical"}, submission=s5)

    # 6. jurisdiction mismatch
    s6 = make_sub("US", "Pinecrest Industrial Tools Inc", "pinecrest-tools.com", 106, inc_days=1400,
                  tax={"tax_id": "GB123456789", "tax_id_type": "VAT"},
                  bank={"iban": make_iban("GB", "BARC20040052431876"), "swift_bic": "BARCGB22", "bank_name": "Barclays",
                        "bank_country": "GB"})
    del s6["bank"]["account_number"], s6["bank"]["routing_number"]
    s6["documents"][0] = {"doc_type": "TAX_CERTIFICATE", "filename": "vat_certificate.pdf",
                          "extracted": {"name_on_document": "Pinecrest Industrial Tools Inc", "id_number": "GB123456789", "issue_date": _d(300)}}
    S["6_jurisdiction_mismatch"] = dict(
        title="Jurisdiction mismatch", tests="Tax-ID format vs claimed country",
        description="Company claims the US but supplies a UK VAT number and a UK IBAN. The message says which country the "
                    "tax ID belongs to and asks for a US EIN plus W-9.",
        expected={"status": "Pending", "decision_type": "needs_vendor_action"}, submission=s6)

    # 7. conflicting soft signals
    s7 = make_sub("AE", "Sandstone Trading FZE", None, 107, inc_days=41,
                  contact={"email": "sandstone.trading@gmail.com"})
    S["7_soft_signals"] = dict(
        title="Conflicting soft signals", tests="Escalation to a human",
        description="Valid TRN and IBAN, matching holder - but gmail contact, incorporated 41 days ago and no website. "
                    "Three WARNs, no ERROR/CRITICAL: escalated to a reviewer instead of auto-decided.",
        expected={"status": "Pending", "decision_type": "needs_human_review"}, submission=s7)

    # 8. fuzzy watchlist hit
    s8 = make_sub("GB", "Volgograd Trade Company", "volgogradtrade.co.uk", 108, inc_days=1000)
    S["8_watchlist_fuzzy"] = dict(
        title="Fuzzy watchlist hit", tests="Fuzzy sanctions screening (CRITICAL)",
        description="'Volgograd Trade Company' is not an exact match to watchlist entry 'Volgograd Trading Co' - fuzzy "
                    "matching flags it anyway and shows the matched entry.",
        expected={"status": "Rejected", "decision_type": "rejected_critical"}, submission=s8)
    return S


def write_sample_files() -> None:
    SAMPLES_DIR.mkdir(exist_ok=True)
    for key, s in build_samples().items():
        (SAMPLES_DIR / f"{key}.json").write_text(json.dumps(s["submission"], indent=2, ensure_ascii=False))


# ---------------------------------------------------------------- historical runs
def build_history() -> list[dict]:
    """~15 varied runs, oldest first. `parent_idx` links a resubmission to an earlier entry."""
    H: list[dict] = []
    add = lambda days, sub, **kw: H.append(dict(days_ago=days, sub=sub, **kw))

    add(13, make_sub("IN", "Apex Fasteners Pvt Ltd", "apexfasteners.in", 201, inc_days=3000))
    add(12, make_sub("US", "Lakeshore Packaging Inc", "lakeshorepack.com", 202, inc_days=2500))
    add(11, make_sub("DE", "Rheinblick Maschinen GmbH", "rheinblick-maschinen.de", 203, inc_days=4000))
    add(10, make_sub("GB", "Thames Valley Print Ltd", "thamesvalleyprint.co.uk", 204, inc_days=1800))
    add(9, make_sub("AE", "Gulfstream Cargo FZE", "gulfstreamcargo.ae", 205, inc_days=400))
    add(8, make_sub("IN", "Kaveri Textile Mills Pvt Ltd", "kaveri-mills.in", 206, inc_days=5000,
                    contact={"email": "ap@kaveritextiles.com"}))
    h7 = make_sub("IN", "Lotus Agro Foods Pvt Ltd", "lotusagro.in", 207, inc_days=1700)
    corrected = copy.deepcopy(h7)
    del h7["tax"]["pan"]
    add(7, h7)                                           # index 6 -> pending (missing PAN)
    h8 = make_sub("DE", "Nordlicht Systems GmbH", "nordlicht-systems.de", 208, inc_days=2100)
    h8["bank"]["iban"] = h8["bank"]["iban"][:-1] + str((int(h8["bank"]["iban"][-1]) + 1) % 10)
    add(6, h8)
    add(5, make_sub("US", "Bluebird Digital LLC", None, 209, inc_days=30, contact={"email": "hello.bluebird@gmail.com"}))
    h10 = make_sub("IN", "Shree Ganesh Traders Pvt Ltd", "shreeganesh.in", 210, inc_days=2600)
    g = h10["tax"]["tax_id"]
    h10["tax"]["tax_id"] = g[:-1] + ("A" if g[-1] != "A" else "B")
    add(5, h10)
    add(4, make_sub("GB", "Red Meridian Holdings Limited", "redmeridian.co.uk", 211, inc_days=900))
    add(3, make_sub("US", "Summit Ridge Equipment LLC", "summitridge.com", 212, holder="Daniel Whitaker", inc_days=1300))
    h13 = make_sub("US", "Harbor Point Marine LLC", "harborpointmarine.com", 213, inc_days=1900)
    add(3, h13, copy_bank_from=1)                        # steals Lakeshore's account
    add(2, make_sub("US", "Orchard Lane Foods Inc", "orchardlanefoods.com", 214, inc_days=2300))
    add(1, corrected, parent_idx=6)                      # resubmission of Lotus Agro
    return H


def seed_history() -> None:
    ids: list[str] = []
    subs: list[dict] = []
    from .pipeline import create_run, execute_run
    now = datetime.now(timezone.utc)
    for i, h in enumerate(build_history()):
        sub = h["sub"]
        if "copy_bank_from" in h:
            src = subs[h["copy_bank_from"]]
            for k in ("account_number", "routing_number", "bank_name"):
                sub["bank"][k] = src["bank"].get(k)
            sub["documents"][1]["extracted"]["id_number"] = src["bank"]["account_number"]
        subs.append(sub)
        started = now - timedelta(days=h["days_ago"], hours=random.Random(i).randint(0, 6), minutes=random.Random(i).randint(0, 59))
        parent = ids[h["parent_idx"]] if "parent_idx" in h else None
        rid = create_run(sub, parent, started)
        execute_run(rid, delay_ms=0)
        ids.append(rid)


def init_app(seed_runs: bool = True) -> None:
    db.init_schema()
    if db.vendors_count() == 0:
        base = datetime.now(timezone.utc) - timedelta(days=400)
        for v in ref.EXISTING_VENDORS:
            db.insert_vendor(v, "master", None, base.isoformat(timespec="milliseconds"))
    if seed_runs and os.environ.get("SEED_HISTORY", "1") != "0" and db.runs_count() == 0:
        seed_history()
    try:
        write_sample_files()
    except OSError:
        pass


if __name__ == "__main__":  # `make seed`
    init_app()
    write_sample_files()
    print(f"Database ready at {db.db_path()} with {db.runs_count()} runs; sample JSON written to {SAMPLES_DIR}")
