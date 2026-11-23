"""Reference data: existing vendor master, watchlist, country rules (all fictional / mock)."""
from __future__ import annotations

from .validators import make_gstin

COUNTRY_NAMES = {"IN": "India", "US": "United States", "GB": "United Kingdom",
                 "DE": "Germany", "AE": "United Arab Emirates"}

WATCHLIST = [
    "Volgograd Trading Co",
    "Karakol Shipping FZE",
    "Red Meridian Holdings Ltd",
    "Aurelian Metals Trading LLC",
    "Nordvik Export Partners",
]
WATCHLIST_THRESHOLD = 0.88

FREE_EMAIL_DOMAINS = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "proton.me"}

IFSC_BANKS = {"HDFC": "hdfc bank", "ICIC": "icici bank", "SBIN": "state bank of india", "UTIB": "axis bank"}

# country -> required tax-id / bank fields / documents (mirrored in static/app.js)
REQUIRED_DOCS = {
    "IN": ["TAX_CERTIFICATE", "BANK_LETTER"],
    "US": ["W9", "BANK_LETTER"],
    "GB": ["TAX_CERTIFICATE", "BANK_LETTER"],
    "DE": ["TAX_CERTIFICATE", "BANK_LETTER"],
    "AE": ["TAX_CERTIFICATE", "BANK_LETTER"],
}
DOC_LABELS = {
    "TAX_CERTIFICATE": {
        "IN": "GST registration certificate", "GB": "VAT registration certificate",
        "DE": "VAT registration certificate (USt-IdNr. confirmation)",
        "AE": "UAE tax registration (TRN) certificate", "US": "tax registration certificate",
    },
    "W9": "IRS Form W-9", "BANK_LETTER": "Bank letter", "INCORPORATION_CERT": "Certificate of incorporation",
    "W8BEN": "IRS Form W-8BEN", "OTHER": "Other document",
}
DOC_ACTIONS = {
    "TAX_CERTIFICATE": "Upload the official {label} showing your legal name and tax ID.",
    "W9": "Upload a completed and signed IRS Form W-9 for the legal entity.",
    "BANK_LETTER": ("Upload a bank letter on the bank's letterhead (issued within the last 12 months) "
                    "confirming the account holder name and account number/IBAN."),
}

# Existing approved-vendor master. Fixed so that sample 5 collides with Cascade.
CASCADE_ACCOUNT = "000123456789"
CASCADE_ROUTING = "021000021"
HELIX_IBAN = "DE89370400440532013000"
ORBIT_GSTIN = make_gstin("27", "AABCO1234F")

EXISTING_VENDORS = [
    {"name": "Cascade Industrial Supply LLC", "country": "US", "tax_id": "84-1234567",
     "account_number": CASCADE_ACCOUNT, "iban": None, "routing": CASCADE_ROUTING, "ifsc": None},
    {"name": "Helix Packaging GmbH", "country": "DE", "tax_id": "DE123456789",
     "account_number": None, "iban": HELIX_IBAN, "routing": None, "ifsc": None},
    {"name": "Orbit Stationers Pvt Ltd", "country": "IN", "tax_id": ORBIT_GSTIN,
     "account_number": "50100123456789", "iban": None, "routing": None, "ifsc": "HDFC0001234"},
]
