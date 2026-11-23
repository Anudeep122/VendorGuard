"""SQLite persistence (stdlib sqlite3)."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, submission_json TEXT, status TEXT, decision_type TEXT,
  started_at TEXT, finished_at TEXT, parent_run_id TEXT, vendor_name TEXT, country TEXT,
  summary TEXT, risk_score INTEGER, duration_ms INTEGER, decision_json TEXT
);
CREATE TABLE IF NOT EXISTS stage_results (
  run_id TEXT, stage_key TEXT, status TEXT, started_at TEXT, finished_at TEXT,
  findings_json TEXT, passes_json TEXT, PRIMARY KEY (run_id, stage_key)
);
CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, rule_id TEXT, severity TEXT,
  message TEXT, evidence_json TEXT, stage_key TEXT, action TEXT
);
CREATE TABLE IF NOT EXISTS emails (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, audience TEXT, kind TEXT,
  subject TEXT, body TEXT, to_addr TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS vendors (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, country TEXT, tax_id TEXT,
  account_number TEXT, iban TEXT, routing TEXT, ifsc TEXT, source TEXT, run_id TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
  run_id TEXT, seq INTEGER, type TEXT, data_json TEXT, PRIMARY KEY (run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at);
CREATE INDEX IF NOT EXISTS idx_findings_run ON findings(run_id);
"""


def db_path() -> str:
    return os.environ.get("DB_PATH", "./data/vendorguard.db")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@contextmanager
def conn():
    p = db_path()
    d = os.path.dirname(os.path.abspath(p))
    os.makedirs(d, exist_ok=True)
    c = sqlite3.connect(p, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def init_schema() -> None:
    with conn() as c:
        try:
            c.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass
        c.executescript(SCHEMA)


def j(v: Any) -> str:
    return json.dumps(v, default=str, ensure_ascii=False)


def _loads(s: Optional[str], default=None):
    try:
        return json.loads(s) if s else default
    except Exception:
        return default


# ---------------------------------------------------------------- runs
def insert_run(run_id: str, raw: Any, parent_run_id: Optional[str], vendor_name: str,
               country: Optional[str], started_at: str) -> None:
    with conn() as c:
        c.execute("INSERT INTO runs (id, submission_json, status, started_at, parent_run_id, vendor_name, country) "
                  "VALUES (?,?,?,?,?,?,?)",
                  (run_id, j(raw), "Running", started_at, parent_run_id, vendor_name, country))


def finish_run(run_id: str, status: str, decision_type: str, finished_at: str, summary: str,
               risk_score: int, duration_ms: int, decision: dict, vendor_name: str, country: Optional[str],
               submission: Any = None) -> None:
    with conn() as c:
        c.execute("UPDATE runs SET status=?, decision_type=?, finished_at=?, summary=?, risk_score=?, "
                  "duration_ms=?, decision_json=?, vendor_name=?, country=? WHERE id=?",
                  (status, decision_type, finished_at, summary, risk_score, duration_ms, j(decision),
                   vendor_name, country, run_id))
        if submission is not None:
            c.execute("UPDATE runs SET submission_json=? WHERE id=?", (j(submission), run_id))


def get_run_row(run_id: str) -> Optional[dict]:
    with conn() as c:
        r = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    return dict(r) if r else None


def add_stage_result(run_id, key, status, started_at, finished_at, findings, passes) -> None:
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO stage_results VALUES (?,?,?,?,?,?,?)",
                  (run_id, key, status, started_at, finished_at, j(findings), j(passes)))
        for f in findings:
            c.execute("INSERT INTO findings (run_id, rule_id, severity, message, evidence_json, stage_key, action) "
                      "VALUES (?,?,?,?,?,?,?)",
                      (run_id, f["rule_id"], f["severity"], f["message"], j(f.get("evidence")), key, f.get("action")))


def add_email(run_id: str, e: dict) -> None:
    with conn() as c:
        c.execute("INSERT INTO emails (run_id, audience, kind, subject, body, to_addr, source) VALUES (?,?,?,?,?,?,?)",
                  (run_id, e.get("audience"), e.get("kind"), e["subject"], e["body"], e.get("to"), e.get("source")))


def add_event(run_id: str, etype: str, data: Any) -> None:
    with conn() as c:
        seq = c.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE run_id=?", (run_id,)).fetchone()[0]
        c.execute("INSERT INTO events VALUES (?,?,?,?)", (run_id, seq, etype, j(data)))


def get_events(run_id: str, after: int = 0) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT seq, type, data_json FROM events WHERE run_id=? AND seq>? ORDER BY seq",
                         (run_id, after)).fetchall()
    return [{"seq": r["seq"], "type": r["type"], "data": _loads(r["data_json"], {})} for r in rows]


def run_detail(run_id: str) -> Optional[dict]:
    run = get_run_row(run_id)
    if not run:
        return None
    with conn() as c:
        stages = c.execute("SELECT * FROM stage_results WHERE run_id=? ORDER BY rowid", (run_id,)).fetchall()
        emails = c.execute("SELECT * FROM emails WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
        kids = c.execute("SELECT id, vendor_name, status, started_at FROM runs WHERE parent_run_id=? "
                         "ORDER BY started_at", (run_id,)).fetchall()
    run["submission"] = _loads(run.pop("submission_json"), {})
    run["decision"] = _loads(run.pop("decision_json"), None)
    run["stages"] = [{"key": s["stage_key"], "status": s["status"], "started_at": s["started_at"],
                      "finished_at": s["finished_at"], "findings": _loads(s["findings_json"], []),
                      "passes": _loads(s["passes_json"], [])} for s in stages]
    run["findings"] = [dict(f, stage_key=s["key"]) for s in run["stages"] for f in s["findings"]]
    run["emails"] = [{"audience": e["audience"], "kind": e["kind"], "subject": e["subject"], "body": e["body"],
                      "to": e["to_addr"], "source": e["source"]} for e in emails]
    run["children"] = [dict(k) for k in kids]
    return run


def list_runs(status=None, search=None, country=None, since=None, until=None, limit=500) -> list[dict]:
    q = ("SELECT id, vendor_name, country, status, decision_type, risk_score, started_at, finished_at, "
         "duration_ms, parent_run_id, summary FROM runs WHERE 1=1")
    args: list[Any] = []
    if status:
        q += " AND LOWER(status)=LOWER(?)"; args.append(status)
    if country:
        q += " AND country=?"; args.append(country.upper())
    if search:
        q += " AND (LOWER(vendor_name) LIKE ? OR id LIKE ?)"; args += [f"%{search.lower()}%", f"%{search}%"]
    if since:
        q += " AND started_at>=?"; args.append(since)
    if until:
        q += " AND started_at<=?"; args.append(until + ("T23:59:59" if len(until) == 10 else ""))
    q += " ORDER BY started_at DESC LIMIT ?"
    args.append(max(1, min(int(limit), 2000)))
    with conn() as c:
        return [dict(r) for r in c.execute(q, args).fetchall()]


def stats() -> dict:
    with conn() as c:
        done = "status IN ('Approved','Pending','Rejected')"
        total = c.execute(f"SELECT COUNT(*) FROM runs WHERE {done}").fetchone()[0]
        by_status = {r[0]: r[1] for r in c.execute(f"SELECT status, COUNT(*) FROM runs WHERE {done} GROUP BY status")}
        by_country = {r[0] or "?": r[1] for r in c.execute(
            f"SELECT country, COUNT(*) FROM runs WHERE {done} GROUP BY country")}
        by_type = {r[0]: r[1] for r in c.execute(
            f"SELECT decision_type, COUNT(*) FROM runs WHERE {done} GROUP BY decision_type")}
        top = [{"rule_id": r[0], "severity": r[1], "count": r[2]} for r in c.execute(
            "SELECT rule_id, MAX(CASE severity WHEN 'CRITICAL' THEN 3 WHEN 'ERROR' THEN 2 ELSE 1 END) sv, COUNT(*) n "
            "FROM findings WHERE severity IN ('WARN','ERROR','CRITICAL') GROUP BY rule_id ORDER BY n DESC, rule_id LIMIT 8")]
        for t in top:
            t["severity"] = {3: "CRITICAL", 2: "ERROR", 1: "WARN"}[t["severity"]]
        avg = c.execute(f"SELECT AVG(duration_ms) FROM runs WHERE {done}").fetchone()[0]
        per_day = [{"date": r[0], "count": r[1]} for r in c.execute(
            f"SELECT substr(started_at,1,10) d, COUNT(*) FROM runs WHERE {done} GROUP BY d ORDER BY d DESC LIMIT 14")][::-1]
    return {"total": total, "by_status": by_status, "by_country": by_country, "by_decision_type": by_type,
            "top_rules": top, "avg_duration_ms": avg or 0, "runs_per_day": per_day,
            "needs_human_review": by_type.get("needs_human_review", 0)}


# ---------------------------------------------------------------- vendors
def vendors_count() -> int:
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM vendors").fetchone()[0]


def runs_count() -> int:
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM runs").fetchone()[0]


def insert_vendor(v: dict, source: str, run_id: Optional[str], created_at: Optional[str] = None) -> None:
    with conn() as c:
        c.execute("INSERT INTO vendors (name, country, tax_id, account_number, iban, routing, ifsc, source, run_id, created_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (v["name"], v.get("country"), v.get("tax_id"), v.get("account_number"), v.get("iban"),
                   v.get("routing"), v.get("ifsc"), source, run_id, created_at or now_iso()))


def find_vendors(account_number: Optional[str] = None, iban: Optional[str] = None,
                 tax_id: Optional[str] = None) -> dict[str, list[dict]]:
    """Return vendors sharing the (normalized) bank account / IBAN / tax id."""
    import re
    n = lambda s: re.sub(r"[^A-Z0-9]", "", (s or "").upper())
    with conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM vendors").fetchall()]
    out = {"bank": [], "tax": []}
    for r in rows:
        if (account_number and n(r["account_number"]) == n(account_number)) or (iban and n(r["iban"]) == n(iban)):
            out["bank"].append(r)
        if tax_id and n(r["tax_id"]) == n(tax_id):
            out["tax"].append(r)
    return out
