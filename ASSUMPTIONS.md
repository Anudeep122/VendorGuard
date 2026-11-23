# Assumptions and thresholds

| Area | Assumption |
|---|---|
| Countries | IN, US, GB, DE, AE only; anything else fails intake (`INTAKE_SCHEMA`) |
| Name match | `similarity` = max(token_set_ratio, ratio) on normalised names, 0–1. Suffix words (pvt, private, ltd, limited, llc, inc, gmbh, fze, co, company…) and "and"/"&" are dropped; trade/trader/traders → trading so "Volgograd Trade Company" ≈ "Volgograd Trading Co" |
| Holder vs legal name | ≥ 0.90 pass · acronym/trading-name match pass with INFO · 0.70–0.90 WARN · < 0.70 and looks like a person → CRITICAL · else ERROR |
| Person heuristic | 2–3 capitalised alphabetic tokens, no legal suffix, no company keyword, not similar to company name |
| Watch-list | fuzzy score ≥ 0.88 on legal name, trading name or account holder → CRITICAL. Uses stricter `name_match_score` (no "subset = 100" quirk). Entries are fictional |
| Duplicates | same bank account/IBAN under a name with similarity < 0.70 → CRITICAL; ≥ 0.70 → WARN `RISK_DUPLICATE_VENDOR`. Same tax ID under a different name → CRITICAL |
| New company | incorporated < 90 days ago → WARN (includes the day count); future date → ERROR |
| Bank letter | issue date > 12 months old → WARN |
| Document checks | name < 0.80 vs legal name → ERROR (tax/other docs only); bank-letter holder < 0.85 vs account holder → WARN; a document of the wrong type is flagged once and not further checked |
| No website | INFO normally. **Deviation:** escalated to WARN when the contact email is a free provider (no verifiable online identity) — needed so the "Sandstone Trading FZE" scenario has exactly three WARNs |
| Phone | plausible E.164 (8–15 digits); invalid → ERROR |
| WARN escalation | 0 WARN → approved_clean, 1 → approved_with_notes, ≥ 2 → needs_human_review |
| Crashed check | `STAGE_EXCEPTION` never approves; routes to needs_human_review |
| Risk score | CRITICAL 60, ERROR 15, WARN 10, INFO 0, capped at 100; display only |
| Vendor master | Cascade Industrial Supply LLC, Helix Packaging GmbH, Orbit Stationers Pvt Ltd (fictional); approved runs are added |
| Historical seed | ~15 runs produced by the real pipeline on generated vendors distinct from the 8 samples, timestamps back-dated |
| Processing time | dashboard shows rules-engine time, excluding the artificial `STAGE_DELAY_MS` |
| Uploads | stored; fields extracted only if an LLM is configured, otherwise `extracted = {}` with a note |
| Emails | drafts only, never sent |
