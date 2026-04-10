"""Prompt templates for AI decision calls."""
from __future__ import annotations

import json
from typing import Any

from ..core.knowledge import PerformanceState


def build_triads_prompt(triads: dict) -> str:
    """Return a readable triad framing for prompts."""
    lines = ["The three lenses guiding your decision:"]
    for name, info in triads.items():
        lines.append(f"  - **{name}**: {info['description']}")
        lines.append(f"    Bias: {info['bias']} | Strength: {info['strength']}")
    return "\n".join(lines)


def build_state_prompt(state: PerformanceState) -> str:
    """Return current performance state summary."""
    return (
        f"Current phase: {state.phase}\n"
        f"Target energy: {state.energy_level:.2f}\n"
        f"Audience engagement: {state.audience_engagement:.2f}\n"
        f"Allowed outputs: {state.constraints.get('allowed_outputs', ['lights','audio','display'])}\n"
    )


def build_constraints_prompt(constraints: dict[str, Any]) -> str:
    """Return active constraints for prompt."""
    lines = ["Active constraints:"]
    for key, value in constraints.items():
        lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def build_patterns_prompt(patterns: list[dict]) -> str:
    """Return learned patterns formatted for prompt."""
    if not patterns:
        return "No learned patterns yet."
    lines = ["Learned patterns from past performances:"]
    for p in patterns[-5:]:
        lines.append(f"  - [{p.get('trigger','unknown')}] {p.get('outcome','')} (success: {p.get('success',0):.2f})")
    return "\n".join(lines)


def build_decision_prompt(
    message: dict,
    state: PerformanceState,
    triads: dict,
    patterns: list[dict],
    constraints: dict[str, Any],
) -> str:
    """Build full decision prompt for an external LLM call."""
    return "\n".join([
        "You are assisting the Good Theatre Engine — an AI-orchestrated live performance system.",
        "Your role is to recommend output commands based on incoming events.",
        "",
        "## INCOMING EVENT",
        json.dumps(message, indent=2),
        "",
        "## CURRENT PERFORMANCE STATE",
        build_state_prompt(state),
        "",
        "## ACTIVE CONSTRAINTS",
        build_constraints_prompt(constraints),
        "",
        "## LEARNED PATTERNS",
        build_patterns_prompt(patterns),
        "",
        "## DECISION LENSES",
        build_triads_prompt(triads),
        "",
        "## YOUR TASK",
        "Analyse the incoming event against state, constraints, and patterns.",
        "Recommend 1-3 output commands (target, action, parameters).",
        "Consider: energy balance, audience engagement, phase context, and triad tensions.",
        "Respond with a JSON array of commands.",
        "",
        "Example response:",
        json.dumps([
            {"target": "lights", "action": "fade", "channel": 1, "target_value": 0.75, "duration": 1.5},
            {"target": "display", "text": "Climax building", "style": "alert"},
        ], indent=2),
    ])


def build_feedback_prompt(
    event: dict,
    outcome: str,
    state_after: PerformanceState,
) -> str:
    """Build feedback prompt for learning after a performance."""
    return "\n".join([
        "Performance reflection — what worked and what didn't?",
        "",
        "## EVENT THAT TRIGGERED",
        json.dumps(event, indent=2),
        "",
        "## OUTCOME",
        outcome,
        "",
        "## STATE AFTER",
        build_state_prompt(state_after),
        "",
        "## YOUR TASK",
        "Summarise the lesson learned in 1-2 sentences.",
        "Give it a success score 0.0-1.0.",
        "What would you do differently next time?",
    ])
