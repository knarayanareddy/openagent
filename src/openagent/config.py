"""Runtime configuration from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    home: Path
    provider: str  # anthropic | openai | scripted
    model: str
    small_model: str
    owner: str
    max_iterations: int = 10

    @staticmethod
    def from_env() -> "Config":
        home = Path(os.environ.get("OPENAGENT_HOME", "~/.openagent")).expanduser()
        provider = os.environ.get("OPENAGENT_PROVIDER", "").strip().lower()
        model = os.environ.get("OPENAGENT_MODEL", "").strip()
        small_model = os.environ.get("OPENAGENT_SMALL_MODEL", "").strip()
        owner = os.environ.get("OPENAGENT_OWNER", "local:owner")

        if not provider:
            if os.environ.get("ANTHROPIC_API_KEY"):
                provider = "anthropic"
            elif os.environ.get("OPENAI_API_KEY"):
                provider = "openai"
            else:
                provider = "scripted"

        if not model:
            model = "claude-sonnet-4-5" if provider == "anthropic" else "gpt-4o-mini" if provider == "openai" else "scripted"
        if not small_model:
            small_model = model

        return Config(
            home=home,
            provider=provider,
            model=model,
            small_model=small_model,
            owner=owner,
            max_iterations=int(os.environ.get("OPENAGENT_MAX_ITERATIONS", "10")),
        )
