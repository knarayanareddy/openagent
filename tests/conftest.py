"""Shared fixtures. Run from the prototypes/fusion directory:  python -m pytest -q"""

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from openagent.agent import Fusion  # noqa: E402
from openagent.testing import ScriptedLLM  # noqa: E402

NOW = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
OWNER = "telegram:1001"
ME = {"via": "telegram", "chat_id": 1001}


@pytest.fixture
def llm():
    return ScriptedLLM()


@pytest.fixture
def fusion(tmp_path, llm):
    return Fusion(tmp_path / "home", llm, owner=OWNER, every_n=50)
