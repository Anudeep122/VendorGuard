import pytest

from app import db, seed
from app.pipeline import run_pipeline

SAMPLES = seed.build_samples()


def run(key, parent=None):
    rid = run_pipeline(SAMPLES[key]["submission"], parent, delay_ms=0)
    return db.run_detail(rid)


def sev(d, rule):
    return [f["severity"] for f in d["findings"] if f["rule_id"] == rule]


@pytest.mark.parametrize("key", [k for k in SAMPLES if k != "3b_resubmission"])
def test_expected_outcome(key):
    d = run(key)
    exp = SAMPLES[key]["expected"]
    assert (d["status"], d["decision_type"]) == (exp["status"], exp["decision_type"])
    assert d["decision"]["reasoning"] or d["status"] == "Approved"


def test_s1_clean_has_no_warnings():
    d = run("1_clean")
    assert not [f for f in d["findings"] if f["severity"] in ("WARN", "ERROR", "CRITICAL")]
    assert len(db.find_vendors(tax_id=SAMPLES["1_clean"]["submission"]["tax"]["tax_id"])["tax"]) == 1  # vendor inserted


def test_s2_acronym_info_and_one_warn():
    d = run("2_name_variant")
    assert sev(d, "CROSS_ACCOUNT_HOLDER_NAME") == ["INFO"]
    assert sum(f["severity"] == "WARN" for f in d["findings"]) == 1


def test_s3_three_errors_and_email_lists_each():
    d = run("3_incomplete_wrong_doc")
    errs = [f for f in d["findings"] if f["severity"] == "ERROR"]
    assert len(errs) == 3
    assert {f["rule_id"] for f in errs} == {"COMPLETENESS_MISSING_FIELD", "COMPLETENESS_MISSING_DOC", "DOC_TYPE_MISMATCH"}
    body = d["emails"][0]["body"].lower()
    assert d["emails"][0]["audience"] == "vendor"
    assert "swift" in body and "electricity_bill_oct.pdf" in body and "bank letter" in body
    assert "1." in body and "2." in body and "3." in body


def test_s3b_resubmission_approved_and_linked():
    parent = run("3_incomplete_wrong_doc")
    d = run("3b_resubmission", parent["id"])
    assert (d["status"], d["decision_type"]) == ("Approved", "approved_clean")
    assert d["parent_run_id"] == parent["id"]
    assert any(f["rule_id"] == "RESUBMISSION" for f in d["findings"])
    from app.main import _resolved
    r = _resolved(d)
    assert len(r["resolved"]) == 3 and not r["still_open"]


def test_s4_individual_critical_and_neutral_vendor_email():
    d = run("4_individual_account")
    assert sev(d, "CROSS_ACCOUNT_HOLDER_NAME") == ["CRITICAL"]
    vendor = next(e for e in d["emails"] if e["audience"] == "vendor")
    internal = next(e for e in d["emails"] if e["audience"] == "internal")
    assert "fraud" not in vendor["body"].lower() and "markus" not in vendor["body"].lower()
    assert "Markus Vogel" in internal["body"]


def test_s5_duplicate_bank_names_existing_vendor():
    d = run("5_duplicate_bank")
    f = next(f for f in d["findings"] if f["rule_id"] == "RISK_DUPLICATE_BANK")
    assert f["severity"] == "CRITICAL" and f["evidence"]["existing_vendor"] == "Cascade Industrial Supply LLC"


def test_s6_names_gb_and_requests_ein_w9():
    d = run("6_jurisdiction_mismatch")
    f = next(f for f in d["findings"] if f["rule_id"] == "FORMAT_TAXID_COUNTRY")
    assert f["evidence"]["detected_country"] == "GB"
    body = d["emails"][0]["body"]
    assert "United Kingdom" in body and "EIN" in body and "W-9" in body


def test_s7_three_warns_internal_review_email():
    d = run("7_soft_signals")
    warns = {f["rule_id"] for f in d["findings"] if f["severity"] == "WARN"}
    assert warns == {"RISK_FREE_EMAIL", "RISK_NEW_COMPANY", "RISK_NO_WEBSITE"}
    assert not [f for f in d["findings"] if f["severity"] in ("ERROR", "CRITICAL")]
    assert {e["audience"] for e in d["emails"]} == {"internal", "vendor"}
    new = next(f for f in d["findings"] if f["rule_id"] == "RISK_NEW_COMPANY")
    assert new["evidence"]["days_since_incorporation"] == 41


def test_s8_watchlist_shows_matched_entry():
    d = run("8_watchlist_fuzzy")
    f = next(f for f in d["findings"] if f["rule_id"] == "RISK_WATCHLIST")
    assert f["severity"] == "CRITICAL" and f["evidence"]["matched_entry"] == "Volgograd Trading Co"


def test_rerun_approved_vendor_flags_duplicate():
    run("1_clean")
    d = run("1_clean")
    assert sev(d, "RISK_DUPLICATE_VENDOR") == ["WARN"]
    assert d["decision_type"] == "approved_with_notes"


def test_history_seed_runs_and_is_varied():
    seed.seed_history()
    runs = db.list_runs()
    assert len(runs) >= 14
    assert {r["status"] for r in runs} == {"Approved", "Pending", "Rejected"}
    assert any(r["parent_run_id"] for r in runs)
    assert any(r["decision_type"] == "needs_human_review" for r in runs)
