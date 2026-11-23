"""Pipeline orchestrator: runs the 8 stages, emits events, persists everything."""
from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from . import db
from .stages import communication, completeness, cross_checks, decision, documents, format_checks, intake, risk_checks
from .stages import risk_checks as _r  # noqa

log = logging.getLogger("vendorguard.pipeline")

STAGES = [
    ("intake", "Intake & normalization", intake.run),
    ("completeness", "Completeness", completeness.run),
    ("format", "Format validation", format_checks.run),
    ("cross", "Cross-field consistency", cross_checks.run),
    ("risk", "Risk & fraud signals", risk_checks.run),
    ("documents", "Document checks", documents.run),
    ("decision", "Decision", decision.run),
    ("communication", "Communication", communication.run),
]
STAGE_LABELS = {k: l for k, l, _ in STAGES}
SKIPPABLE = {"completeness", "format", "cross", "risk", "documents"}


class Ctx:
    def __init__(self, run_id: str, raw: Any, parent_run_id: Optional[str], started_at: str):
        self.run_id, self.raw, self.parent_run_id, self.started_at = run_id, raw, parent_run_id, started_at
        self.sub: Optional[dict] = None
        self.parent: Optional[dict] = None
        self.findings: list[dict] = []
        self.passes: dict[str, list[str]] = {}
        self.stage = ""
        self.abort = False
        self.decision: Optional[dict] = None
        self.emails: list[dict] = []

    def ok(self, text: str) -> None:
        self.passes.setdefault(self.stage, []).append(text)


def _vendor_and_country(raw: Any) -> tuple[str, Optional[str]]:
    try:
        c = raw.get("company") or {}
        name = c.get("legal_name") if isinstance(c, dict) else None
        cc = c.get("country") if isinstance(c, dict) else None
        return (str(name)[:200] if name else "(unnamed vendor)"), (str(cc).upper()[:3] if cc else None)
    except Exception:
        return "(unnamed vendor)", None


def create_run(raw: Any, parent_run_id: Optional[str] = None, started_at: Optional[datetime] = None) -> str:
    run_id = uuid.uuid4().hex[:10]
    name, cc = _vendor_and_country(raw)
    ts = (started_at or datetime.now(timezone.utc)).isoformat(timespec="milliseconds")
    db.insert_run(run_id, raw, parent_run_id, name, cc, ts)
    return run_id


def _stage_status(findings: list[dict]) -> str:
    sevs = {f["severity"] for f in findings}
    if sevs & {"ERROR", "CRITICAL"}:
        return "error"
    return "warn" if "WARN" in sevs else "ok"


def execute_run(run_id: str, delay_ms: Optional[int] = None) -> None:
    """Run the full pipeline for an already-created run. Never raises."""
    t0 = time.perf_counter()
    row = db.get_run_row(run_id)
    if not row:
        return
    import json
    raw = json.loads(row["submission_json"]) if row["submission_json"] else {}
    ctx = Ctx(run_id, raw, row["parent_run_id"], row["started_at"])
    delay = (int(os.environ.get("STAGE_DELAY_MS", "600")) if delay_ms is None else delay_ms) / 1000.0
    try:
        for key, label, fn in STAGES:
            ctx.stage = key
            st = db.now_iso()
            if ctx.abort and key in SKIPPABLE:
                db.add_stage_result(run_id, key, "skipped", st, st, [], ["Skipped: submission could not be parsed"])
                db.add_event(run_id, "stage_finished", {"stage_key": key, "label": label, "status": "skipped",
                                                        "findings": [], "passes": ["Skipped: submission could not be parsed"],
                                                        "duration_ms": 0})
                continue
            db.add_event(run_id, "stage_started", {"stage_key": key, "label": label})
            if delay:
                time.sleep(delay)
            s0 = time.perf_counter()
            try:
                found = fn(ctx) or []
            except Exception as e:  # a crashing stage must never crash the run
                log.exception("stage %s crashed", key)
                found = [{"rule_id": "SYSTEM_STAGE_FAILURE", "severity": "ERROR",
                          "message": f"Automated check '{label}' could not complete ({type(e).__name__}); manual review required.",
                          "evidence": {"system": True, "stage": key}, "action": None}]
            for f in found:
                f["stage_key"] = key
            ctx.findings.extend(found)
            status = _stage_status(found)
            if key == "decision" and ctx.decision:
                status = {"Approved": "ok", "Pending": "warn", "Rejected": "error"}[ctx.decision["status"]]
            db.add_stage_result(run_id, key, status, st, db.now_iso(), found, ctx.passes.get(key, []))
            db.add_event(run_id, "stage_finished", {
                "stage_key": key, "label": label, "status": status, "findings": found,
                "passes": ctx.passes.get(key, []), "duration_ms": int((time.perf_counter() - s0) * 1000)})
            if key == "decision" and ctx.decision:
                db.add_event(run_id, "decision", ctx.decision)
            if key == "communication":
                for e in ctx.emails:
                    db.add_email(run_id, e)
                    db.add_event(run_id, "email", e)
    except Exception as e:  # absolute last resort
        log.exception("pipeline crashed")
        if not ctx.decision:
            ctx.decision = decision.decide([{"rule_id": "SYSTEM_PIPELINE_FAILURE", "severity": "ERROR",
                                             "message": f"Pipeline failed unexpectedly ({type(e).__name__}).",
                                             "evidence": {"system": True}}])

    d = ctx.decision or decision.decide([])
    dur = int((time.perf_counter() - t0) * 1000)
    name, cc = _vendor_and_country(ctx.sub or raw)
    db.finish_run(run_id, d["status"], d["decision_type"], db.now_iso(), d["summary"], d["risk_score"], dur, d, name, cc,
                  submission=ctx.sub or None)
    db.add_event(run_id, "run_finished", {"run_id": run_id, "status": d["status"], "decision_type": d["decision_type"],
                                          "duration_ms": dur})


def run_pipeline(raw: Any, parent_run_id: Optional[str] = None, started_at: Optional[datetime] = None,
                 delay_ms: Optional[int] = None) -> str:
    run_id = create_run(raw, parent_run_id, started_at)
    execute_run(run_id, delay_ms)
    return run_id
