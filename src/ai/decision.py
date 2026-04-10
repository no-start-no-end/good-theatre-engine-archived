"""Decision engine with pattern weighting and zone-aware behaviour."""
from __future__ import annotations

from typing import Any

from .triads import TRIAADS
from ..core.knowledge import KnowledgeBase
from ..core.message import MessageType, UniversalMessage, output_command


class DecisionEngine:
    """Makes decisions based on messages, knowledge, triads, and learned patterns.

    Each incoming message is interpreted through the three triad lenses.
    Matching patterns from past performances weight the command selection.
    The engine records outcomes so patterns can improve over time.
    """

    def __init__(self, knowledge: KnowledgeBase, triads: dict = TRIAADS):
        self.knowledge = knowledge
        self.triads = triads

    def process(self, message: UniversalMessage, knowledge_context: dict) -> list[UniversalMessage]:
        """Full decision pipeline: interpret → match patterns → decide → constrain → emit."""
        interpretation = self._interpret(message, knowledge_context)
        patterns = self.knowledge.get_patterns(interpretation["trigger"])
        decision = self._decide(interpretation, patterns)
        constrained = self._apply_constraints(decision["commands"])
        decision["commands"] = constrained
        outputs = self._generate_commands(decision)

        if decision.get("record_pattern"):
            self.knowledge.log_pattern(
                decision["trigger"],
                decision["summary"],
                decision["success_score"],
            )

        return outputs

    def record_outcome(self, trigger: str, command_taken: dict, success: float):
        """Record what actually happened so patterns can learn."""
        self.knowledge.log_pattern(trigger, f"command={command_taken.get('target')}", success)

    # ------------------------------------------------------------------
    # Internal steps
    # ------------------------------------------------------------------

    def _interpret(self, message: UniversalMessage, context: dict) -> dict[str, Any]:
        state = context.get("state", {})
        energy = float(state.get("energy_level", 0.5))
        movement = float(message.payload.get("movement_level", 0.0))
        text = str(message.payload.get("text", "")).lower()
        zone = message.payload.get("zone", "unknown")
        urgency = "high" if movement > 0.7 or "tension" in text else "medium" if movement > 0.3 else "low"

        # Triad balance weights shift the decision envelope
        tri_bal = {
            "impatient_artist": min(1.0, energy + 0.2),
            "small_dog": max(movement, 0.2),
            "robot_perspective": 1.0 - min(0.8, movement / 1.25),
        }

        return {
            "trigger": message.source,
            "urgency": urgency,
            "energy": energy,
            "movement": movement,
            "message_type": message.type.value,
            "text": text,
            "zone": zone,
            "triad_balance": tri_bal,
        }

    def _decide(self, interpretation: dict, patterns: list[dict]) -> dict[str, Any]:
        """Select commands using pattern success as weighting + triad balance."""
        avg_success = (
            sum(p.get("success", 0.5) for p in patterns) / len(patterns)
            if patterns else 0.5
        )
        tri = interpretation["triad_balance"]
        urgency = interpretation["urgency"]
        text = interpretation.get("text", "")
        zone = interpretation.get("zone", "unknown")
        movement = interpretation["movement"]
        energy = interpretation["energy"]

        commands: list[dict[str, Any]] = []

        # Base action derived from urgency/text — then weight by pattern success
        if "soften" in text or urgency == "low":
            base_weight = avg_success
            commands = self._apply_pattern_weights([
                {"target": "lights", "action": "fade", "channel": 1, "target_value": 0.35, "duration": 2.0, "base": 0.5},
                {"target": "display", "text": "Hold the breath of the room", "style": "calm", "base": 0.5},
            ], patterns, base_weight)
        elif "tension" in text or urgency == "high":
            # High urgency: triad imbalance toward impatient_artist — go bigger
            if tri["impatient_artist"] > 0.6:
                commands = [
                    {"target": "lights", "action": "fade", "channel": 1, "target_value": 0.9, "duration": 0.6},
                    {"target": "audio", "action": "play_note", "channel": 1, "note": 72, "velocity": 96},
                    {"target": "display", "text": "Escalate", "style": "alert"},
                ]
            else:
                commands = [
                    {"target": "lights", "action": "fade", "channel": 1, "target_value": 0.75, "duration": 1.0},
                    {"target": "display", "text": "Rising tension", "style": "normal"},
                ]
        else:
            # Medium / neutral — robot_perspective dampens if movement is low
            commands = [
                {"target": "audio", "action": "set_volume", "channel": 1, "volume": 0.4},
                {"target": "display", "text": "Stay responsive", "style": "normal"},
            ]
            if tri["robot_perspective"] > 0.7:
                commands.append({"target": "lights", "action": "fade", "channel": 1, "target_value": 0.5, "duration": 3.0})

        # Zone-aware bonus: stage-zone motion demands different response than audience
        if zone.startswith("stage") and movement > 0.5:
            commands.insert(0, {"target": "lights", "action": "fade", "channel": 2, "target_value": 0.8, "duration": 1.0})

        return {
            "trigger": interpretation["trigger"],
            "summary": f"urgency={urgency}, zone={zone}, learned_success={avg_success:.2f}",
            "success_score": avg_success,
            "record_pattern": True,
            "commands": commands,
        }

    def _apply_pattern_weights(
        self,
        candidates: list[dict[str, Any]],
        patterns: list[dict],
        base_weight: float,
    ) -> list[dict[str, Any]]:
        """Order candidates by pattern success, highest first."""
        if not patterns:
            return candidates

        def weighted_success(c: dict[str, Any]) -> float:
            target = c.get("target", "")
            matching = [p for p in patterns if target in p.get("outputs", [])]
            if not matching:
                return base_weight
            return max(p.get("success", base_weight) for p in matching)

        return sorted(candidates, key=weighted_success, reverse=True)

    def _apply_constraints(self, commands: list[dict]) -> list[dict]:
        constraints = self.knowledge.load_state().constraints
        max_volume = float(constraints.get("max_volume", 0.8))
        min_transition = float(constraints.get("min_lighting_transition", 0.5))
        max_light = float(constraints.get("max_light_level", 1.0))
        adjusted = []
        for command in commands:
            command = dict(command)
            if command.get("target") == "audio" and "volume" in command:
                command["volume"] = min(max_volume, float(command["volume"]))
            if command.get("target") == "lights":
                if "target_value" in command:
                    command["target_value"] = min(max_light, float(command["target_value"]))
                command["duration"] = max(min_transition, float(command.get("duration", min_transition)))
            adjusted.append(command)
        return adjusted

    def _generate_commands(self, decision: dict) -> list[UniversalMessage]:
        messages: list[UniversalMessage] = []
        for command in decision["commands"]:
            target = command["target"]
            payload = {k: v for k, v in command.items() if k != "target"}
            if "target_value" in payload:
                payload["value"] = payload.pop("target_value")
            messages.append(output_command(target, payload, source="decision.engine"))
        return messages
