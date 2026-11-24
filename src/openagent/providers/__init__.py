"""LLM provider adapters.

The core loop speaks one internal dialect (Anthropic-style content blocks).
Providers translate to/from external APIs.
"""
from openagent.providers.anthropic import AnthropicProvider
from openagent.providers.openai import OpenAIProvider

__all__ = ["AnthropicProvider", "OpenAIProvider"]
