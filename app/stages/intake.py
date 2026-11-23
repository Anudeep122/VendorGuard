"""Stage 1 - schema validation + normalization."""
from __future__ import annotations

import re
import uuid

from pydantic import ValidationError

from .. import db
from ..models import Submission, finding
from ..validators import clean_iban

SCHEMA_ACTION = "Resubmit the vendor form as valid JSON that follows the documented structure and supported countries."


def _schema_fail(ctx, message, evidence=None):
    ctx.abort = True
    return [finding("INTAKE_SCHEMA", "ERROR", message, evidence or {}, SCHEMA_ACTION)]


def normalize(d: dict) -> dict:
    c, t, bk, ct = d["company"], d["tax"], d["bank"], d["contact"]
    up = lambda v: v.upper().strip() if isinstance(v, str) else v
    t["tax_id"] = re.sub(r"\s", "", up(t["tax_id"])) if t.get("tax_id") else None
    t["tax_id_type"] = up(t.get("tax_id_type"))
    t["pan"] = re.sub(r"\s", "", up(t["pan"])) if t.get("pan") else None
    bk["iban"] = clean_iban(bk["iban"]) if bk.get("iban") else None
    bk["account_number"] = re.sub(r"[\s-]", "", bk["account_number"]) if bk.get("account_number") else None
    bk["swift_bic"] = re.sub(r"\s", "", up(bk["swift_bic"])) if bk.get("swift_bic") else None
    bk["ifsc"] = re.sub(r"\s", "", up(bk["ifsc"])) if bk.get("ifsc") else None
    bk["routing_number"] = re.sub(r"[\s-]", "", bk["routing_number"]) if bk.get("routing_number") else None
    if ct.get("email"):
        ct["email"] = ct["email"].lower().strip()
    if ct.get("phone"):
        ct["phone"] = ct["phone"].strip()
    if c.get("website"):
        c["website"] = c["website"].strip()
    if c["address"].get("postal_code"):
        c["address"]["postal_code"] = c["address"]["postal_code"].upper()
    d["submission_id"] = d.get("submission_id") or uuid.uuid4().hex[:8]
    return d


def run(ctx):
    raw = ctx.raw
    if not isinstance(raw, dict):
        return _schema_fail(ctx, "The submission is not a JSON object.", {"received_type": type(raw).__name__})
    if "_malformed_body" in raw:
        return _schema_fail(ctx, "The request body is not valid JSON.", {"excerpt": str(raw["_malformed_body"])[:120]})
    if not raw:
        return _schema_fail(ctx, "The submission is empty.")
    try:
        model = Submission.model_validate(raw)
    except ValidationError as e:
        errs = [{"field": ".".join(str(p) for p in er["loc"]), "problem": er["msg"]} for er in e.errors()[:8]]
        first = errs[0]
        more = f" (+{len(e.errors()) - 1} more)" if len(e.errors()) > 1 else ""
        return _schema_fail(ctx, f"Submission failed schema validation: '{first['field']}' - {first['problem']}{more}.",
                            {"errors": errs})
    except Exception as e:  # pathological input
        return _schema_fail(ctx, "Submission could not be parsed.", {"error": type(e).__name__})

    ctx.sub = normalize(model.model_dump(mode="json"))
    ctx.ok("Schema valid; identifiers and contact fields normalized")
    out = []
    pid = ctx.sub.get("parent_run_id") or ctx.parent_run_id
    if pid:
        parent = db.run_detail(pid)
        if parent:
            ctx.parent = parent
            prev = [f["message"] for f in parent["findings"] if f["severity"] in ("ERROR", "CRITICAL")]
            out.append(finding("RESUBMISSION", "INFO",
                               f"Resubmission of run {pid}; previous issues: " + ("; ".join(prev) if prev else "none"),
                               {"parent_run_id": pid, "parent_status": parent["status"], "previous_issues": prev}))
        else:
            out.append(finding("RESUBMISSION", "INFO", f"Resubmission references unknown parent run '{pid}'.",
                               {"parent_run_id": pid}))
    return out
