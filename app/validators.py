"""Identifier validators and (for samples/tests) generators of *valid* identifiers.

Every ``*_problem`` function returns ``None`` when the value is valid, otherwise a
short human-readable reason. ``is_valid_*`` are boolean wrappers.
"""
from __future__ import annotations

import re

_B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
SWIFT_RE = re.compile(r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$")
EIN_RE = re.compile(r"^\d{2}-?\d{7}$")
GB_VAT_RE = re.compile(r"^GB\d{9}$")
DE_VAT_RE = re.compile(r"^DE\d{9}$")
AE_TRN_RE = re.compile(r"^\d{15}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")

IBAN_LENGTHS = {"DE": 22, "GB": 22, "AE": 23}
VALID_GST_STATE_CODES = {f"{i:02d}" for i in range(1, 39)} | {"97", "99"}

TAXID_RES = {"IN": GSTIN_RE, "US": EIN_RE, "GB": GB_VAT_RE, "DE": DE_VAT_RE, "AE": AE_TRN_RE}
TAXID_LABELS = {"IN": "GSTIN", "US": "US EIN", "GB": "UK VAT", "DE": "German VAT", "AE": "UAE TRN"}
TAXID_EXAMPLES = {
    "IN": "15-character GSTIN, e.g. 27AAPFU0939F1ZV",
    "US": "EIN as NN-NNNNNNN, e.g. 12-3456789",
    "GB": "GB followed by 9 digits",
    "DE": "DE followed by 9 digits",
    "AE": "15-digit TRN",
}


def norm_id(s) -> str:
    """Upper-case and strip spaces/dashes so identifiers compare reliably."""
    return re.sub(r"[\s\-]", "", str(s or "")).upper()


def clean_iban(s) -> str:
    return re.sub(r"\s", "", str(s or "")).upper()


def shape_matches(country: str, tax_id: str | None) -> bool:
    rx = TAXID_RES.get(country)
    return bool(rx and tax_id and rx.match(str(tax_id).strip().upper().replace(" ", "")))


def detect_taxid_countries(tax_id: str | None) -> list[str]:
    return [cc for cc in TAXID_RES if shape_matches(cc, tax_id)]


def detect_taxid_country(tax_id: str | None):
    found = detect_taxid_countries(tax_id)
    return found[0] if found else None


# ---------------------------------------------------------------- GSTIN / PAN
def gstin_checksum_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        val = _B36.index(ch)
        prod = val * (1 if i % 2 == 0 else 2)
        total += prod // 36 + prod % 36
    return _B36[(36 - total % 36) % 36]


def gstin_problem(g: str | None) -> str | None:
    if not g:
        return "empty"
    g = g.strip().upper()
    if len(g) != 15:
        return f"must be 15 characters (got {len(g)})"
    if not GSTIN_RE.match(g):
        return "does not match the GSTIN pattern (2 digits, 5 letters, 4 digits, letter, entity, 'Z', check char)"
    if g[:2] not in VALID_GST_STATE_CODES:
        return f"invalid state code {g[:2]}"
    expected = gstin_checksum_char(g[:14])
    if g[14] != expected:
        return f"checksum character is '{g[14]}' but should be '{expected}'"
    return None


def is_valid_gstin(g) -> bool:
    return gstin_problem(g) is None


def is_valid_pan(p) -> bool:
    return bool(p) and bool(PAN_RE.match(p.strip().upper()))


def is_valid_ifsc(i) -> bool:
    return bool(i) and bool(IFSC_RE.match(i.strip().upper()))


def make_gstin(state: str, pan: str, entity: str = "1") -> str:
    """Build a valid GSTIN: state(2) + PAN(10) + entity(1) + 'Z' + checksum."""
    body = f"{state}{pan.upper()}{entity}Z"
    return body + gstin_checksum_char(body)


# ----------------------------------------------------------------------- IBAN
def _iban_mod97(s: str) -> int:
    rearranged = s[4:] + s[:4]
    digits = "".join(str(int(c, 36)) for c in rearranged)
    return int(digits) % 97


def iban_problem(iban: str | None) -> str | None:
    if not iban:
        return "empty"
    s = iban.replace(" ", "").upper()
    if not re.match(r"^[A-Z]{2}\d{2}[A-Z0-9]+$", s):
        return "contains invalid characters"
    cc = s[:2]
    if cc in IBAN_LENGTHS and len(s) != IBAN_LENGTHS[cc]:
        return f"{cc} IBANs must be {IBAN_LENGTHS[cc]} characters (got {len(s)})"
    if len(s) < 15 or len(s) > 34:
        return "length outside the IBAN range"
    if _iban_mod97(s) != 1:
        return "mod-97 checksum failed"
    return None


def is_valid_iban(i) -> bool:
    return iban_problem(i) is None


def make_iban(cc: str, bban: str) -> str:
    """Build a valid IBAN from a country code and BBAN (check digits are computed)."""
    cc = cc.upper()
    rearr = bban.upper() + cc + "00"
    digits = "".join(str(int(c, 36)) for c in rearr)
    check = 98 - int(digits) % 97
    return f"{cc}{check:02d}{bban.upper()}"


# ------------------------------------------------------------------ SWIFT etc
def is_valid_swift(b) -> bool:
    return bool(b) and bool(SWIFT_RE.match(b.strip().upper()))


def is_valid_ein(e) -> bool:
    return bool(e) and bool(EIN_RE.match(e.strip()))


def aba_problem(r: str | None) -> str | None:
    if not r:
        return "empty"
    r = r.strip()
    if not re.match(r"^\d{9}$", r):
        return "must be exactly 9 digits"
    d = [int(c) for c in r]
    total = 3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])
    if total % 10 != 0:
        return "ABA checksum failed"
    return None


def is_valid_aba(r) -> bool:
    return aba_problem(r) is None


def make_aba(prefix8: str) -> str:
    d = [int(c) for c in prefix8]
    partial = 3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + d[2] + d[5]
    for c in range(10):
        if (partial + c) % 10 == 0:
            return prefix8 + str(c)
    raise AssertionError


def is_valid_email(e) -> bool:
    return bool(e) and bool(EMAIL_RE.match(e.strip()))


def is_valid_phone(p) -> bool:
    if not p:
        return False
    return bool(PHONE_RE.match(re.sub(r"[\s().\-]", "", p)))


POSTAL_RES = {
    "IN": re.compile(r"^\d{6}$"),
    "US": re.compile(r"^\d{5}(-\d{4})?$"),
    "GB": re.compile(r"^[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}$", re.I),
    "DE": re.compile(r"^\d{5}$"),
}


def postal_ok(country: str, code: str | None) -> bool:
    rx = POSTAL_RES.get(country)
    if rx is None or not code:
        return True
    return bool(rx.match(code.strip()))


# ------------------------------------------------- check_* (None == valid)
def _bad(ok: bool, reason: str):
    return None if ok else reason


def check_gstin(g):
    return gstin_problem(g)


def check_pan(p):
    return _bad(is_valid_pan(p), "must be 5 letters, 4 digits, 1 letter (e.g. ABCDE1234F)")


def check_ifsc(i):
    return _bad(is_valid_ifsc(i), "must be 4 letters, a zero, then 6 alphanumerics (e.g. HDFC0001234)")


def check_iban(i):
    return iban_problem(i)


def check_bic(b):
    return _bad(is_valid_swift(b), "must be 8 or 11 characters: 4 letters, 2-letter country, 2 alphanumerics, optional 3")


def check_aba(r):
    return aba_problem(r)


def check_email(e):
    return _bad(is_valid_email(e), "not a valid email address")


def check_phone(p):
    return _bad(is_valid_phone(p), "expected an international number such as +91 98765 43210")


def check_postal(country: str, code):
    return _bad(postal_ok(country, code), f"unexpected postal-code format for {country}")


def is_valid_postal(code, country) -> bool:
    return postal_ok(country, code)


def is_valid_gb_vat(x) -> bool:
    return shape_matches("GB", x)


def is_valid_de_vat(x) -> bool:
    return shape_matches("DE", x)


def is_valid_ae_trn(x) -> bool:
    return shape_matches("AE", x)
