"""Prompt builder for external AI operators."""
from __future__ import annotations

import json

from ..core.knowledge import PerformanceState
from ..core.message import UniversalMessage


def build_decision_prompt(message: UniversalMessage, state: PerformanceState, patterns: list[dict], triads: dict) -> str:
    """Build a structured prompt without calling a model."""
    return "\n".join([
        "You are assisting a live theatre orchestration engine.",
        "Balance surprise, room sensitivity, and system coherence.",
        "",
        "Incoming message:",
        json.dumps(message.to_dict(), indent=2),
        "",
        "Current performance state:",
        json.dumps(state.to_dict(), indent=2),
        "",
        "Relevant learned patterns:",
        json.dumps(patterns, indent=2),
        "",
        "Triad lenses:",
        json.dumps(triads, indent=2),
        "",
        "Respond with: interpretation, risks, and recommended commands.",
    ])
