"""openagent — a personal agent harness built from proven open-source patterns.

Provenance: this package combines ideas from several open-source projects.
Upstream names and paths are kept in module docstrings for attribution.

  ShenSeanChen/waku-agent   loop, retrieval gate, FTS5 memory, inbox/outbox, approvals, eval style
  NousResearch/hermes-agent bounded curated memory, write-time scan, frozen prompt snapshot
  HKUDS/nanobot             dream cursor, git-audited memory, schedule kinds
  openclaw/openclaw         active-hours window, defer-not-drop semantics
  qwibitai/nanoclaw         ALLOW/DENY/HOLD guard, replay rule, command gate, circuit breaker
  NevaMind-AI/memU          wiki export for diffable memory

No Waku name/mark or hosted/ ELv2 code is included. See NOTICE.md.
"""
from openagent.agent import Fusion, Turn
from openagent.guard import Guard
from openagent.llm import LLM, Response
from openagent.testing import ScriptedLLM
from openagent.tools import ToolRegistry, default_tools, default_rules

__all__ = [
    "Fusion", "Turn", "Guard", "LLM", "Response", "ScriptedLLM",
    "ToolRegistry", "default_tools", "default_rules",
]
__version__ = "0.1.0"
