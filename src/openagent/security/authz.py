"""Simple ingress authz policy skeleton.

Target model: token/principal -> role/scope -> allowed sessions/sources/actions.
This is a minimal in-repo baseline; extend for production policy needs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch


@dataclass(frozen=True)
class Principal:
    name: str
    token: str
    scopes: set[str] = field(default_factory=set)
    allow_sessions: list[str] = field(default_factory=lambda: ["*"])
    allow_sources: list[str] = field(default_factory=lambda: ["*"])


@dataclass(frozen=True)
class AuthzDecision:
    allowed: bool
    principal: str = ""
    reason: str = ""


class AuthzPolicy:
    def __init__(self, principals: list[Principal] | None = None, default_allow: bool = False) -> None:
        self.principals = principals or []
        self.default_allow = default_allow

    def authenticate(self, token: str) -> Principal | None:
        for p in self.principals:
            if token and p.token and token == p.token:
                return p
        return None

    def authorize(self, principal: Principal | None, *, action: str, session_id: str, source: str) -> AuthzDecision:
        if principal is None:
            return AuthzDecision(self.default_allow, reason="unknown principal" if not self.default_allow else "default allow")
        if action not in principal.scopes and "*" not in principal.scopes:
            return AuthzDecision(False, principal=principal.name, reason=f"missing scope {action}")
        if not any(fnmatch(session_id, pat) for pat in principal.allow_sessions):
            return AuthzDecision(False, principal=principal.name, reason="session not allowed")
        if not any(fnmatch(source, pat) for pat in principal.allow_sources):
            return AuthzDecision(False, principal=principal.name, reason="source not allowed")
        return AuthzDecision(True, principal=principal.name)
