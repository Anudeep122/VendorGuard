"""FastAPI app: REST API + SSE stream + static single-page UI."""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import db, llm, seed
from .pipeline import STAGE_LABELS, STAGES, create_run, execute_run

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
MAX_BODY = 2_000_000


@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_in_threadpool(seed.init_app)
    yield


app = FastAPI(title="VendorGuard", version="1.0", lifespan=lifespan)


async def _parse_body(request: Request) -> Any:
    """Never raises: malformed JSON becomes a marker the intake stage turns into a graceful Pending run."""
    body = await request.body()
    if len(body) > MAX_BODY:
        return {"_malformed_body": "request body too large"}
    if not body.strip():
        return {}
    try:
        return json.loads(body)
    except Exception:
        return {"_malformed_body": body[:300].decode("utf-8", "replace")}


def _resolve_sample(name: str) -> tuple[dict, Optional[str]]:
    samples = seed.build_samples()
    if name not in samples:
        raise HTTPException(404, f"Unknown sample '{name}'")
    s = samples[name]
    parent_id = None
    if s.get("parent_sample"):
        psample = samples[s["parent_sample"]]
        pname = psample["submission"]["company"]["legal_name"]
        rows = [r for r in db.list_runs(search=pname) if r["vendor_name"] == pname and r["status"] == "Pending"]
        if rows:
            parent_id = rows[0]["id"]
        else:  # run the parent first so the resubmission demo always works
            from .pipeline import run_pipeline
            parent_id = run_pipeline(psample["submission"], None, None, delay_ms=0)
    return s["submission"], parent_id


@app.get("/health")
def health():
    return {"status": "ok", "llm_provider": llm.provider()}


@app.post("/api/runs")
async def create(request: Request, background: BackgroundTasks):
    raw = await _parse_body(request)
    parent = None
    if isinstance(raw, dict) and set(raw.keys()) == {"sample"} and isinstance(raw["sample"], str):
        raw, parent = await run_in_threadpool(_resolve_sample, raw["sample"])
    run_id = await run_in_threadpool(create_run, raw, parent)
    background.add_task(execute_run, run_id)
    return {"run_id": run_id}


@app.post("/api/runs/{run_id}/resubmit")
async def resubmit(run_id: str, request: Request, background: BackgroundTasks):
    if not await run_in_threadpool(db.get_run_row, run_id):
        raise HTTPException(404, "Parent run not found")
    raw = await _parse_body(request)
    if isinstance(raw, dict) and "_malformed_body" not in raw:
        raw["parent_run_id"] = run_id
    new_id = await run_in_threadpool(create_run, raw, run_id)
    background.add_task(execute_run, new_id)
    return {"run_id": new_id, "parent_run_id": run_id}


@app.get("/api/runs/{run_id}/stream")
async def stream(run_id: str, request: Request):
    if not await run_in_threadpool(db.get_run_row, run_id):
        raise HTTPException(404, "Run not found")
    try:
        last = int(request.headers.get("last-event-id", "0"))
    except ValueError:
        last = 0

    async def gen():
        nonlocal last
        idle = 0.0
        yield "retry: 1500\n\n"
        while True:
            events = await asyncio.to_thread(db.get_events, run_id, last)
            for e in events:
                last = e["seq"]
                idle = 0.0
                yield f"id: {e['seq']}\nevent: {e['type']}\ndata: {json.dumps(e['data'], default=str)}\n\n"
                if e["type"] == "run_finished":
                    return
            if await request.is_disconnected():
                return
            idle += 0.15
            if idle > 120:
                yield "event: timeout\ndata: {}\n\n"
                return
            if int(idle / 0.15) % 100 == 99:
                yield ": keepalive\n\n"
            await asyncio.sleep(0.15)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


@app.get("/api/runs")
def list_runs(status: Optional[str] = None, search: Optional[str] = None, country: Optional[str] = None,
              since: Optional[str] = None, until: Optional[str] = None, limit: int = 500):
    return db.list_runs(status, search, country, since, until, limit)


def _resolved(detail: dict) -> Optional[dict]:
    pid = detail.get("parent_run_id")
    parent = pid and db.run_detail(pid)
    if not parent:
        return None
    key = lambda f: (f["rule_id"], f["message"])
    now = {key(f) for f in detail["findings"] if f["severity"] in ("ERROR", "CRITICAL")}
    prev = [f for f in parent["findings"] if f["severity"] in ("ERROR", "CRITICAL")]
    return {"parent": {"id": parent["id"], "vendor_name": parent["vendor_name"], "status": parent["status"],
                       "decision_type": parent["decision_type"]},
            "resolved": [{"rule_id": f["rule_id"], "message": f["message"]} for f in prev if key(f) not in now],
            "still_open": [{"rule_id": f["rule_id"], "message": f["message"]} for f in prev if key(f) in now]}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    d = db.run_detail(run_id)
    if not d:
        raise HTTPException(404, "Run not found")
    d["resubmission"] = _resolved(d)
    d["stage_labels"] = STAGE_LABELS
    return d


@app.get("/api/runs/{run_id}/export")
def export(run_id: str):
    d = db.run_detail(run_id)
    if not d:
        raise HTTPException(404, "Run not found")
    d["resubmission"] = _resolved(d)
    return JSONResponse(d, headers={"Content-Disposition": f'attachment; filename="vendorguard-{run_id}.json"'})


@app.get("/api/stats")
def stats():
    return db.stats()


@app.get("/api/samples")
def samples():
    return [dict(key=k, **{x: v[x] for x in ("title", "description", "tests", "expected", "submission")},
                 parent_sample=v.get("parent_sample")) for k, v in seed.build_samples().items()]


@app.get("/api/meta")
def meta():
    return {"stages": [{"key": k, "label": l} for k, l, _ in STAGES], "llm_provider": llm.provider()}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 10_000_000:
        raise HTTPException(413, "File too large (max 10 MB)")
    updir = Path(os.environ.get("UPLOAD_DIR", Path(db.db_path()).parent / "uploads"))
    updir.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch for ch in (file.filename or "upload") if ch.isalnum() or ch in "._-")[:80] or "upload"
    stored = f"{uuid.uuid4().hex[:8]}_{safe}"
    (updir / stored).write_bytes(data)
    mime = file.content_type or "application/octet-stream"
    extracted = await run_in_threadpool(llm.extract_document_fields, data, mime) if llm.available() else None
    if extracted:
        return {"filename": file.filename, "stored_as": stored, "extracted": extracted, "doc_type": extracted.get("doc_type"),
                "note": "Fields extracted by AI - please verify."}
    return {"filename": file.filename, "stored_as": stored, "extracted": {}, "doc_type": None,
            "note": "File stored. No AI extraction available, so content checks will be skipped for this document."}


app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")
