"""Pluggable threat scanning interface.

Baseline is regex/heuristic only. For higher assurance, implement ThreatScanner
with a model/classifier/service and wire it into memory ingestion and recall.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from openagent.memory.curated import scan as regex_scan


@dataclass(frozen=True)
class ThreatVerdict:
    ok: bool
    reason: str = ""
    scanner: str = "unknown"
    confidence: float | None = None


class ThreatScanner(Protocol):
    name: str

    def scan(self, text: str, context: dict | None = None) -> ThreatVerdict: ...


class RegexThreatScanner:
    name = "regex"

    def scan(self, text: str, context: dict | None = None) -> ThreatVerdict:
        reason = regex_scan(text)
        return ThreatVerdict(ok=reason is None, reason=reason or "", scanner=self.name, confidence=1.0 if reason else None)


class CompositeThreatScanner:
    """Run multiple scanners; any non-ok verdict rejects the content."""

    def __init__(self, scanners: list[ThreatScanner] | None = None) -> None:
        self.scanners = scanners or [RegexThreatScanner()]
        self.name = "composite"

    def scan(self, text: str, context: dict | None = None) -> ThreatVerdict:
        for scanner in self.scanners:
            verdict = scanner.scan(text, context=context)
            if not verdict.ok:
                return verdict
        return ThreatVerdict(ok=True, scanner=self.name)
