"""Pydantic v2 submission schema + finding helpers."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

SUPPORTED_COUNTRIES = ["IN", "US", "GB", "DE", "AE"]
DOC_TYPES = ["TAX_CERTIFICATE", "BANK_LETTER", "INCORPORATION_CERT", "W9", "W8BEN", "OTHER"]

Str = Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]]

SEVERITIES = ["INFO", "WARN", "ERROR", "CRITICAL"]
SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}
SEV_SCORE = {"CRITICAL": 60, "ERROR": 15, "WARN": 10, "INFO": 0}


def finding(rule_id: str, severity: str, message: str, evidence: dict | None = None,
            action: str | None = None) -> dict:
    return {"rule_id": rule_id, "severity": severity, "message": message,
            "evidence": evidence or {}, "action": action}


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=True)

    @field_validator("*", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v


class Address(_Base):
    line1: Str = None
    city: Str = None
    postal_code: Str = None
    country: Str = None

    @field_validator("country")
    @classmethod
    def _cc(cls, v):
        return v.upper() if v else v


class Company(_Base):
    legal_name: Str = None
    trading_name: Str = None
    country: Str = None
    registration_number: Str = None
    incorporation_date: Optional[date] = None
    address: Address = Field(default_factory=Address)
    website: Str = None

    @field_validator("country")
    @classmethod
    def _country(cls, v):
        if v is None:
            return v
        v = v.upper()
        if v not in SUPPORTED_COUNTRIES:
            raise ValueError(f"Unsupported country '{v}'. Supported: {', '.join(SUPPORTED_COUNTRIES)}")
        return v


class Tax(_Base):
    tax_id: Str = None
    tax_id_type: Str = None
    pan: Str = None


class Contact(_Base):
    name: Str = None
    email: Str = None
    phone: Str = None


class Bank(_Base):
    bank_name: Str = None
    account_holder: Str = None
    account_number: Str = None
    iban: Str = None
    swift_bic: Str = None
    ifsc: Str = None
    routing_number: Str = None
    bank_country: Str = None

    @field_validator("bank_country")
    @classmethod
    def _cc(cls, v):
        return v.upper() if v else v


class Document(_Base):
    doc_type: str = "OTHER"
    filename: Str = None
    extracted: dict[str, Any] = Field(default_factory=dict)

    @field_validator("doc_type", mode="before")
    @classmethod
    def _dt(cls, v):
        v = (str(v) if v is not None else "OTHER").strip().upper().replace(" ", "_")
        return v if v in DOC_TYPES else "OTHER"

    @field_validator("extracted", mode="before")
    @classmethod
    def _ex(cls, v):
        return v if isinstance(v, dict) else {}


class Submission(_Base):
    submission_id: Str = None
    parent_run_id: Str = None
    company: Company = Field(default_factory=Company)
    tax: Tax = Field(default_factory=Tax)
    contact: Contact = Field(default_factory=Contact)
    bank: Bank = Field(default_factory=Bank)
    documents: list[Document] = Field(default_factory=list, max_length=20)
