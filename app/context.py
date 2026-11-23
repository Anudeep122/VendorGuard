"""Shared run context passed to every stage."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from .models import Finding, Submission


@dataclass
class Ctx:
    run_id: str
    raw: Any
    db: sqlite3.Connection
    today: date
    sub: Optional[Submission] = None
    parent: Optional[dict] = None
    abort: bool = False
    findings: list[Finding] = field(default_factory=list)
    passed: dict[str, list[str]] = field(default_factory=dict)
    decision: dict = field(default_factory=dict)
    emails: list[dict] = field(default_factory=list)

    def f(self, stage: str, rule_id: str, severity: str, message: str,
          evidence: dict | None = None, action: str | None = None) -> Finding:
        fd = Finding(rule_id, severity, message, evidence or {}, stage, action)
        self.findings.append(fd)
        return fd

    def ok(self, stage: str, text: str) -> None:
        self.passed.setdefault(stage, []).append(text)

    def stage_findings(self, stage: str) -> list[Finding]:
        return [x for x in self.findings if x.stage_key == stage]

    @property
    def country(self) -> str | None:
        return self.sub.company.country if self.sub else None
