"""Pattern learner that extracts useful cues from event logs."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from typing import Any

from ..core.knowledge import KnowledgeBase


class PatternLearner:
    """Analyze performance logs and promote useful recurring patterns.

    Svensk kommentar: läraren ska hitta enkla samband efter spelning,
    inte försöka vara magisk mitt i showen.
    """

    def __init__(self, knowledge: KnowledgeBase):
        self.knowledge = knowledge

    def analyze(self, event_log_path: str) -> dict:
        """Analyze an event log and return ranked candidate patterns."""
        path = Path(event_log_path)
        if not path.exists():
            return {"patterns": [], "summary": {"events": 0, "learned": 0}}

        chains: dict[str, dict[str, Any]] = defaultdict(lambda: {"inputs": [], "outputs": [], "system": []})
        total_events = 0
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                total_events += 1
                entry = json.loads(line)
                message = entry.get("message", {})
                trace_id = entry.get("trace_id") or message.get("metadata", {}).get("trace_id") or message.get("id")
                message_type = message.get("type")
                if message_type in {"sensor_event", "human_input"}:
                    chains[trace_id]["inputs"].append(message)
                elif message_type == "output_command":
                    chains[trace_id]["outputs"].append(message)
                else:
                    chains[trace_id]["system"].append(message)

        learned_patterns = []
        for trace_id, chain in chains.items():
            if not chain["inputs"] or not chain["outputs"]:
                continue
            input_message = chain["inputs"][0]
            source = input_message.get("source", "unknown")
            input_action = input_message.get("payload", {}).get("action") or input_message.get("payload", {}).get("text") or source
            output_targets = [output.get("payload", {}).get("target", "unknown") for output in chain["outputs"]]
            success = min(1.0, 0.45 + (0.12 * len(chain["outputs"])) + (0.04 * len(chain["system"])))
            learned_patterns.append(
                {
                    "trace_id": trace_id,
                    "trigger": source,
                    "input": input_action,
                    "outputs": output_targets,
                    "success": round(success, 2),
                    "summary": f"{input_action} led to {', '.join(output_targets)}",
                }
            )

        learned_patterns.sort(key=lambda item: (item["success"], len(item["outputs"])), reverse=True)
        return {
            "patterns": learned_patterns,
            "summary": {"events": total_events, "learned": len(learned_patterns)},
        }

    def learn(self, event_log_path: str):
        """Persist learned patterns to the knowledge base."""
        analysis = self.analyze(event_log_path)
        for pattern in analysis["patterns"]:
            self.knowledge.log_pattern(pattern["trigger"], pattern["summary"], pattern["success"])
        return analysis
