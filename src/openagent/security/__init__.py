"""Security extension points for OpenAgent.

These modules provide in-repo baselines and interfaces for deployment-specific hardening.
"""
from .authz import AuthzDecision, AuthzPolicy, Principal
from .threat_scanner import CompositeThreatScanner, RegexThreatScanner, ThreatScanner, ThreatVerdict, scan_text, wire_default_scanner

__all__ = [
    "scan_text", "wire_default_scanner",
    "AuthzDecision", "AuthzPolicy", "Principal",
    "ThreatScanner", "RegexThreatScanner", "CompositeThreatScanner", "ThreatVerdict",
]
