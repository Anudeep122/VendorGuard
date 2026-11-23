import json
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def wait(client, rid, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = client.get(f"/api/runs/{rid}").json()
        if d["status"] != "Running":
            return d
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_sample_run_and_sse_replay(client):
    rid = client.post("/api/runs", json={"sample": "1_clean"}).json()["run_id"]
    d = wait(client, rid)
    assert d["status"] == "Approved"
    with client.stream("GET", f"/api/runs/{rid}/stream") as r:
        body = "".join(r.iter_text())
    types = [ln.split(": ", 1)[1] for ln in body.splitlines() if ln.startswith("event: ")]
    assert types.count("stage_started") == 8 and types.count("stage_finished") == 8
    assert "decision" in types and "email" in types and types[-1] == "run_finished"
    assert types.index("stage_started") < types.index("decision") < types.index("run_finished")


def test_3b_sample_links_parent_automatically(client):
    rid = client.post("/api/runs", json={"sample": "3b_resubmission"}).json()["run_id"]
    d = wait(client, rid)
    assert d["status"] == "Approved" and d["parent_run_id"]
    assert len(d["resubmission"]["resolved"]) == 3


def test_resubmit_endpoint(client):
    from app import seed
    s3 = seed.build_samples()
    p = client.post("/api/runs", json=s3["3_incomplete_wrong_doc"]["submission"]).json()["run_id"]
    wait(client, p)
    c = client.post(f"/api/runs/{p}/resubmit", json=s3["3b_resubmission"]["submission"]).json()["run_id"]
    d = wait(client, c)
    assert d["parent_run_id"] == p and d["status"] == "Approved"


@pytest.mark.parametrize("payload", [
    b"{not json", b"", b"[]", b"null", b"42", b'"str"', b"{}",
    json.dumps({"company": "oops"}).encode(),
    json.dumps({"company": {"country": "XX", "legal_name": "A"}}).encode(),
    json.dumps({"company": {"legal_name": "x" * 100000, "country": "IN"}}).encode(),
    json.dumps({"company": None, "bank": None, "documents": "nope"}).encode(),
    json.dumps({"company": {"legal_name": "A", "country": "IN", "incorporation_date": "not-a-date"}}).encode(),
    json.dumps({"documents": [{"doc_type": 5, "extracted": "zzz"}], "company": {"country": "DE", "legal_name": "Z GmbH"}}).encode(),
])
def test_robustness_never_500(client, payload):
    r = client.post("/api/runs", content=payload, headers={"content-type": "application/json"})
    assert r.status_code == 200
    d = wait(client, r.json()["run_id"])
    assert d["status"] in ("Pending", "Rejected", "Approved")
    assert d["findings"], "expected at least one finding"
    if payload in (b"{not json", b"", b"[]", b"null", b"42", b"{}") or b"XX" in payload or b"oops" in payload:
        assert d["status"] == "Pending"
        assert any(f["rule_id"] == "INTAKE_SCHEMA" for f in d["findings"])


def test_unknown_country_message(client):
    rid = client.post("/api/runs", json={"company": {"country": "XX", "legal_name": "A"}}).json()["run_id"]
    d = wait(client, rid)
    f = next(f for f in d["findings"] if f["rule_id"] == "INTAKE_SCHEMA")
    assert "Unsupported country" in f["message"]
    assert len(d["emails"]) == 1 and d["decision_type"] == "needs_vendor_action"
    assert all(s["status"] == "skipped" for s in d["stages"] if s["key"] in ("completeness", "format", "cross", "risk", "documents"))


def test_missing_nested_objects_gives_completeness_errors(client):
    rid = client.post("/api/runs", json={"company": {"legal_name": "Foo Ltd", "country": "GB"}}).json()["run_id"]
    d = wait(client, rid)
    assert d["status"] == "Pending"
    assert sum(f["rule_id"] == "COMPLETENESS_MISSING_FIELD" for f in d["findings"]) >= 5


def test_stage_crash_does_not_break_run(client, monkeypatch):
    from app import pipeline
    def boom(ctx): raise RuntimeError("x")
    stages = [(k, l, boom if k == "risk" else f) for k, l, f in pipeline.STAGES]
    monkeypatch.setattr(pipeline, "STAGES", stages)
    from app import seed
    rid = client.post("/api/runs", json=seed.build_samples()["1_clean"]["submission"]).json()["run_id"]
    d = wait(client, rid)
    assert d["status"] == "Pending" and d["decision_type"] == "needs_human_review"


def test_list_stats_export_samples(client):
    from app import seed
    seed.seed_history()
    runs = client.get("/api/runs").json()
    assert len(runs) >= 14
    assert all(r["status"] == "Rejected" for r in client.get("/api/runs?status=Rejected").json())
    assert client.get("/api/runs?search=lotus").json()
    assert all(r["country"] == "US" for r in client.get("/api/runs?country=US").json())
    st = client.get("/api/stats").json()
    assert st["total"] == len(runs) and st["top_rules"] and sum(st["by_status"].values()) == st["total"]
    rid = runs[0]["id"]
    ex = client.get(f"/api/runs/{rid}/export")
    assert "attachment" in ex.headers["content-disposition"] and ex.json()["id"] == rid
    smp = client.get("/api/samples").json()
    assert len(smp) == 9 and all("expected" in s for s in smp)
    assert client.get("/api/runs/doesnotexist").status_code == 404
    assert client.get("/api/runs/doesnotexist/stream").status_code == 404


def test_upload_without_llm(client):
    r = client.post("/api/upload", files={"file": ("bank letter.pdf", b"%PDF-1.4 test", "application/pdf")})
    assert r.status_code == 200 and r.json()["extracted"] == {}


def test_llm_failure_falls_back_to_template(client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "bad-key")
    import httpx
    def fail(*a, **k): raise httpx.ConnectTimeout("timeout")
    monkeypatch.setattr(httpx, "post", fail)
    from app import seed
    rid = client.post("/api/runs", json=seed.build_samples()["1_clean"]["submission"]).json()["run_id"]
    d = wait(client, rid)
    assert d["status"] == "Approved" and d["emails"][0]["source"] == "template"
