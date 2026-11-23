"""Optional LLM helper. Used ONLY for linguistic tasks (email drafting, document notes, field
extraction from uploads). Every function returns None on any problem so callers fall back to
deterministic output. The LLM never influences decisions or severities."""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Any, Optional

import httpx

log = logging.getLogger("vendorguard.llm")
TIMEOUT = 15.0


def provider() -> str:
    p = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if p == "none":
        return "none"
    if p == "anthropic" or (not p and os.environ.get("ANTHROPIC_API_KEY")):
        return "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "none"
    if p == "gemini" or (not p and os.environ.get("GEMINI_API_KEY")):
        return "gemini" if os.environ.get("GEMINI_API_KEY") else "none"
    return "none"


def available() -> bool:
    return provider() != "none"


def _complete(system: str, user: str, max_tokens: int = 900, file: Optional[tuple[bytes, str]] = None) -> Optional[str]:
    prov = provider()
    try:
        if prov == "anthropic":
            content: list[dict] = []
            if file:
                data, mime = file
                kind = "document" if mime == "application/pdf" else "image"
                content.append({"type": kind, "source": {"type": "base64", "media_type": mime,
                                                         "data": base64.b64encode(data).decode()}})
            content.append({"type": "text", "text": user})
            r = httpx.post("https://api.anthropic.com/v1/messages", timeout=TIMEOUT, headers={
                "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
                "content-type": "application/json"}, json={
                "model": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5"), "max_tokens": max_tokens,
                "system": system, "messages": [{"role": "user", "content": content}]})
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json().get("content", []))
        if prov == "gemini":
            model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
            parts: list[dict] = []
            if file:
                parts.append({"inline_data": {"mime_type": file[1], "data": base64.b64encode(file[0]).decode()}})
            parts.append({"text": user})
            r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                           params={"key": os.environ["GEMINI_API_KEY"]}, timeout=TIMEOUT, json={
                "systemInstruction": {"parts": [{"text": system}]}, "contents": [{"parts": parts}],
                "generationConfig": {"maxOutputTokens": max_tokens}})
            r.raise_for_status()
            return "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])
    except Exception as e:  # network, timeout, quota, parse...
        log.warning("LLM call failed (%s): %s", prov, type(e).__name__)
    return None


def _json_from(text: Optional[str]) -> Any:
    if not text:
        return None
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None


def draft_email(context: dict) -> Optional[dict]:
    """context: {audience, kind, vendor, draft:{subject, body}}. Returns {subject, body} or None."""
    if not available():
        return None
    system = ("You polish business emails for a procurement team. Rewrite the draft so it is warm, clear and "
              "concise. Keep EVERY numbered item, identifier, name and requested action exactly as given; do not "
              "add facts, promises or deadlines. For vendor-facing messages never use the words 'fraud', "
              "'suspicious' or 'sanctions'. Reply ONLY with JSON: {\"subject\": str, \"body\": str}.")
    out = _json_from(_complete(system, json.dumps(context, default=str), 900))
    if isinstance(out, dict) and isinstance(out.get("subject"), str) and isinstance(out.get("body"), str):
        if context.get("audience") == "vendor" and re.search(r"fraud|suspicious|sanction", out["body"], re.I):
            return None
        return {"subject": out["subject"][:200], "body": out["body"][:6000]}
    return None


def review_documents(submission: dict) -> Optional[list[dict]]:
    """Returns [{filename, note}] short natural-language notes (informational only)."""
    if not available() or not submission.get("documents"):
        return None
    system = ("You review vendor-onboarding document metadata. For each document write ONE short sentence "
              "noting anything a reviewer should know. Reply ONLY with JSON: [{\"filename\": str, \"note\": str}].")
    payload = {"company": submission.get("company", {}).get("legal_name"), "documents": submission["documents"]}
    out = _json_from(_complete(system, json.dumps(payload, default=str), 600))
    if isinstance(out, list):
        notes = [{"filename": str(o.get("filename", "")), "note": str(o.get("note", ""))[:300]}
                 for o in out if isinstance(o, dict) and o.get("note")]
        return notes or None
    return None


def extract_document_fields(file_bytes: bytes, mime: str) -> Optional[dict]:
    if not available() or mime not in ("application/pdf", "image/png", "image/jpeg", "image/webp"):
        return None
    system = ("Extract fields from this business document. Reply ONLY with JSON: "
              "{\"doc_type\": one of TAX_CERTIFICATE|BANK_LETTER|INCORPORATION_CERT|W9|W8BEN|OTHER, "
              "\"name_on_document\": str, \"id_number\": str, \"issue_date\": \"YYYY-MM-DD\" or \"\"}.")
    out = _json_from(_complete(system, "Extract the fields.", 400, file=(file_bytes, mime)))
    return out if isinstance(out, dict) else None
