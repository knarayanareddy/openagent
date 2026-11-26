"""Pluggable threat scanning interface.

Baseline is regex/heuristic only. For higher assurance, implement ThreatScanner
with a model/classifier/service and wire it into memory ingestion and recall.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from openagent.memory.curated import _regex_scan, set_extra_threat_scanner


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
        reason = _regex_scan(text)
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


_default_scanner: ThreatScanner | None = None


def get_default_threat_scanner() -> ThreatScanner:
    global _default_scanner
    if _default_scanner is None:
        _default_scanner = RegexThreatScanner()
    return _default_scanner


def set_default_threat_scanner(scanner: ThreatScanner | None) -> None:
    global _default_scanner
    _default_scanner = scanner


def scan_text(text: str, context: dict | None = None) -> ThreatVerdict:
    return get_default_threat_scanner().scan(text, context=context)


def wire_default_scanner(scanner: ThreatScanner | None = None) -> ThreatScanner:
    """Install scanner as the process-wide extra scanner for curated/semantic writes."""
    chosen = scanner or get_default_threat_scanner()
    def _hook(text: str, context: dict | None = None):
        verdict = chosen.scan(text, context=context)
        return None if verdict.ok else (verdict.reason or f"rejected by {verdict.scanner}")
    set_extra_threat_scanner(_hook)
    set_default_threat_scanner(chosen)
    return chosen
