"""Company-name matching: normalization, fuzzy similarity, acronym and person detection."""
from __future__ import annotations

import re

from rapidfuzz import fuzz

LEGAL_SUFFIXES = {
    "pvt", "private", "ltd", "limited", "llc", "inc", "incorporated", "corp", "corporation",
    "gmbh", "ag", "llp", "fze", "fzco", "fzc", "co", "company", "plc", "sa", "bv",
}
FILLER = {"and"}
# Light canonicalisation so trivially different forms of the same word compare equal.
CANON = {
    "trade": "trading", "trades": "trading", "trader": "trading", "traders": "trading",
    "supply": "supplies", "service": "services", "solution": "solutions",
}
COMPANY_KEYWORDS = {
    "solutions", "systems", "trading", "logistics", "industries", "industrial", "technologies",
    "technology", "services", "enterprises", "consulting", "group", "holdings", "supplies",
    "components", "analytics", "packaging", "engineering", "exports", "imports", "traders",
    "manufacturing", "textiles", "software", "labs", "partners", "associates", "stationers",
    "shipping", "freight", "foods", "pharma", "motors", "electronics", "construction", "capital",
}


def _tokens(name: str) -> list[str]:
    s = (name or "").lower().replace("&", " ")
    s = re.sub(r"[^\w\s]", " ", s)
    return [t for t in s.split() if t]


def normalize(name: str | None) -> str:
    toks = [CANON.get(t, t) for t in _tokens(name or "")]
    toks = [t for t in toks if t not in LEGAL_SUFFIXES and t not in FILLER]
    return " ".join(toks)


def similarity(a: str | None, b: str | None) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return max(fuzz.token_set_ratio(na, nb), fuzz.ratio(na, nb)) / 100.0


def initials(name: str | None) -> str:
    return "".join(t[0] for t in normalize(name).split() if t)


def is_acronym_match(short: str | None, long: str | None) -> bool:
    s = re.sub(r"[^a-z]", "", normalize(short))
    if len(s) < 2 or " " in normalize(short):
        return False
    return s == initials(long)


def has_legal_suffix(name: str | None) -> bool:
    return any(t in LEGAL_SUFFIXES for t in _tokens(name or ""))


def looks_like_person(name: str | None, company_name: str | None = None) -> bool:
    """Heuristic: 2-3 capitalised alphabetic tokens, no legal suffix, no company keywords."""
    if not name:
        return False
    raw = [t for t in re.split(r"\s+", name.strip()) if t]
    if not 2 <= len(raw) <= 3:
        return False
    if has_legal_suffix(name):
        return False
    low = [re.sub(r"[^a-z]", "", t.lower()) for t in raw]
    if any(t in COMPANY_KEYWORDS for t in low):
        return False
    for t in raw:
        core = t.strip(".")
        if not re.fullmatch(r"[A-Za-zÀ-ÿ'\-]+", core) or not core[0].isupper():
            return False
        if len(core) > 1 and core.isupper():  # ALL-CAPS tokens look like acronyms
            return False
    if company_name and similarity(name, company_name) >= 0.7:
        return False
    return True


def name_match_score(a: str | None, b: str | None) -> float:
    """Stricter score for watch-list screening: avoids token_set's "subset == 100" quirk."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return max(fuzz.ratio(na, nb), fuzz.token_sort_ratio(na, nb)) / 100.0
