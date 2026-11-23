# VendorGuard — automated vendor onboarding review (PS-2)

A vendor submission goes in; a visible 8-stage pipeline runs; the output is **Approved / Pending / Rejected**, with every
decision traced to named rules and evidence. Anything not approved gets a drafted message stating exactly what is needed.
Decisions are **deterministic and rule-based**; an LLM (optional) only polishes wording.

## Process map

```
Submission JSON (form / JSON editor / sample / resubmission)
        │
        ▼
 1 intake ─ schema + normalisation (bad input → Pending, INTAKE_SCHEMA; remaining stages skipped)
 2 completeness ─ country-specific required fields + documents          → ERROR
 3 format ─ GSTIN/PAN/IFSC/IBAN mod-97/SWIFT/EIN/ABA/VAT/TRN/email/phone → ERROR
 4 cross ─ holder-vs-legal name, bank/address/IBAN country, GSTIN↔PAN    → WARN / ERROR / CRITICAL
 5 risk ─ watch-list, duplicate bank/tax ID, free email, new company     → WARN / CRITICAL
 6 documents ─ type, name, ID, bank-letter holder/staleness              → WARN / ERROR
 7 decision ─ ordered rules (below) + risk score (display only)
 8 communication ─ vendor email / internal alert / compliance alert (drafts, never sent)
        │
        ▼
 Approved ── vendor inserted into master (feeds later duplicate checks)
 Pending  ── needs_vendor_action (numbered checklist) | needs_human_review (internal summary)
 Rejected ── neutral vendor message + internal compliance alert
```

Decision order: any CRITICAL → **Rejected** · else any ERROR → **Pending / needs_vendor_action** · else WARN count:
0 → Approved (clean), 1 → Approved (with notes), ≥2 → **Pending / needs_human_review**.
A crashed check (`STAGE_EXCEPTION`) can never auto-approve; it routes to a human.

## Architecture

```
static/ (vanilla JS SPA, Chart.js local) ──HTTP/SSE──► FastAPI (app/main.py)
                                                         │ background thread
                                                         ▼
                                  pipeline.py ─► stages/*.py ─► SQLite (runs, stage_results, findings,
                                       │                          emails, events, vendors)
                                       └─► llm.py (optional, 15 s timeout, always falls back)
```
Events are persisted as they are emitted, so the SSE stream is both live and replayable.

## Run locally

```bash
pip install -r requirements.txt
make test      # 66 tests, STAGE_DELAY_MS=0, no LLM
make run       # http://localhost:8000  (DB created + ~15 historical runs seeded on first start)
make seed      # regenerate samples/*.json (valid checksums, dates relative to today)
```
No API key needed. To enable AI drafting set `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` (or `gemini` + `GEMINI_API_KEY`).

| Env var | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `none` (auto if a key is set) | `anthropic` \| `gemini` \| `none` |
| `STAGE_DELAY_MS` | `600` | pause between stages so the live view is watchable (0 in tests) |
| `DB_PATH` | `./data/vendorguard.db` | SQLite file |
| `SEED_HISTORY` | `1` | seed historical runs when the DB is empty |

## Deploy
`render.yaml` is a one-click Render blueprint (Docker, `/health` check). The Dockerfile also works on Railway/Fly/HF Spaces
(`uvicorn app.main:app --host 0.0.0.0 --port $PORT`). Mount a disk at `/app/data` if history must survive restarts.

## Demo script (exact order)
1. **Samples → 1 Clean submission** → Approved (clean).
2. **3 Incomplete + wrong document** → Pending; email lists the 3 items (missing SWIFT, wrong "tax certificate", missing bank letter).
3. **3b Resubmission** → Approved; run view shows the parent link and which issues were resolved.
4. **4 Individual's name on corporate account** → Rejected (looks fine on the surface; only the cross-check catches it).
5. **5 Bank account already registered** → Rejected (evidence names Cascade Industrial Supply LLC).
6. **7 Conflicting soft signals** → Pending / needs human review (three WARNs, internal summary).
7. **Dashboard** → KPIs, charts, filterable table, audit-trail drawer.

Note: running an *approved* sample twice is flagged the second time (`RISK_DUPLICATE_VENDOR`, correct behaviour). To reset
the demo: stop the server, `rm -rf data`, restart.

## Design decisions
- **Deterministic rules decide; the LLM only assists.** In finance/compliance an auditor must be able to re-derive any
  decision. LLM output cannot change a severity or a status; it drafts wording, adds INFO-only document notes and extracts
  fields from uploads. Vendor-facing AI drafts are screened and fall back to templates if they mention fraud/sanctions.
  Every email carries an "AI-drafted" / "template" badge.
- **Severity model:** INFO (note) · WARN (soft signal) · ERROR (vendor can fix) · CRITICAL (do not onboard). The 0–100 risk score is
  display-only.
- **Escalate instead of forcing a decision:** two or more soft signals together go to a human reviewer with an internal summary.
- **Not naively strict:** suffix variants and acronyms ("NLS Pvt Ltd") pass with an explanatory INFO note.
- **Resubmission loop:** corrected submissions link to the parent run and show resolved vs. still-open issues.
- **Rejections never accuse the vendor;** the detail goes to an internal compliance alert.
- **Never crash on bad input:** malformed JSON, wrong types, unknown country, huge strings → Pending with `INTAKE_SCHEMA`.

## Next steps
Real OCR for uploaded documents, a live sanctions/PEP API, ERP + email integration (actually send drafts), a reviewer queue
with approve/reject buttons, SLA timers and reminders for pending vendor action.

## Known limitations
Sanctions list and vendor master are mock data; uploads are only parsed when an LLM is configured; emails are drafts only;
no authentication. See `ASSUMPTIONS.md`.
