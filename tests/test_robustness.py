"""Bad input must always produce a graceful Pending, never an exception."""
import pytest

from app import db, seed
from app.pipeline import run_pipeline


def go(raw):
    return db.run_detail(run_pipeline(raw, delay_ms=0))


@pytest.mark.parametrize("raw", [None, [], "not an object", 42, {"company": "oops"},
                                 {"company": {"country": "FR", "legal_name": "X"}},
                                 {"company": {"legal_name": "A" * 100000}}])
def test_bad_input_is_pending_with_intake_schema(raw):
    d = go(raw)
    assert d["status"] == "Pending"
    assert any(x["rule_id"] == "INTAKE_SCHEMA" for x in d["findings"])
    assert len(d["stages"]) == 8  # every stage still reports (skipped ones included)


def test_empty_object_is_pending():
    d = go({})
    assert d["status"] == "Pending"


def test_missing_nested_objects():
    assert go({"company": {"legal_name": "Acme", "country": "US"}})["status"] == "Pending"


def test_numbers_are_coerced():
    s = seed.build_samples()["1_clean"]["submission"]
    s["bank"]["account_number"] = 123456789
    assert go(s)["status"] in ("Approved", "Pending", "Rejected")


def test_llm_failure_falls_back_to_template(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "bad-key")
    import httpx

    def boom(*a, **k):
        raise httpx.ConnectTimeout("timeout")

    monkeypatch.setattr(httpx, "post", boom)
    d = go(seed.build_samples()["1_clean"]["submission"])
    assert d["status"] == "Approved"
    assert all(e.get("source") == "template" for e in d["emails"])
