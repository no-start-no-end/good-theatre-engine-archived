"""Performance mode orchestration for a full theatre run."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Iterable
import time

from .ai.decision import DecisionEngine
from .core.interface import InterfaceLayer
from .core.knowledge import KnowledgeBase
from .core.message import MessageType, Priority, UniversalMessage, human_input


class Phase(Enum):
    """Named performance phases — maps to feeling-state region names.

    The enum name (Phase.INTERMISSION) stays stable as an identifier.
    The .value is the canonical region name used in PhaseSpace and dashboard.
    """

    INTRO        = "detecting"
    ACT_1        = "stabilizing"
    INTERMISSION = "suspended"
    ACT_2        = "escalating"
    OUTRO        = "dispersing"


@dataclass
class PerformanceConfig:
    """Configuration for a single performance phase."""

    name: str
    phase: Phase = Phase.INTRO
    target_energy: float = 0.5
    allowed_outputs: list[str] = field(default_factory=lambda: ["lights", "audio"])
    transition_min_duration: float = 3.0
    human_override_priority: bool = True


class PerformanceRunner:
    """Orchestrates phase transitions, safety controls, and state updates.

    Svensk kommentar: den här klassen håller föreställningens ryggrad.
    Alla fasbyten går via samma plats så att människa och system ser samma sanning.
    """

    def __init__(
        self,
        config: PerformanceConfig,
        knowledge: KnowledgeBase,
        interface: InterfaceLayer,
        decision_engine: DecisionEngine,
        phase_configs: dict[Phase, PerformanceConfig] | None = None,
    ):
        self.config = config
        self.knowledge = knowledge
        self.interface = interface
        self.decision_engine = decision_engine
        self.phase_configs = phase_configs or {config.phase: config}
        self._running = False
        self._paused = False
        self._phase_start: float | None = None
        self._started_at: float | None = None
        self.emergency = False
        self.timeline: list[dict] = []

    def start(self):
        """Begin the performance."""
        self._running = True
        self._paused = False
        self.emergency = False
        self._started_at = datetime.now().timestamp()
        self._phase_start = self._started_at
        self._apply_config(self.config, reset_timer=True)
        self._emit_control_event("performance_start", {"name": self.config.name, "phase": self.config.phase.value})

    def transition_to(self, new_phase: Phase):
        """Transition to a new phase with fade and cleanup."""
        phase_config = self.phase_configs.get(new_phase)
        if phase_config is None:
            raise ValueError(f"Unknown phase config: {new_phase.value}")
        old_phase = self.config.phase
        if self._phase_start is not None:
            elapsed = datetime.now().timestamp() - self._phase_start
            minimum = float(self.config.transition_min_duration)
            if elapsed < minimum:
                time.sleep(max(0.0, minimum - elapsed))
        self._apply_config(phase_config, reset_timer=True)
        self._emit_control_event("phase_transition", {"from": old_phase.value, "to": new_phase.value})

    def emergency_stop(self):
        """Hard stop, cut all outputs immediately."""
        self._running = False
        self._paused = True
        self.emergency = True
        state = self.knowledge.load_state()
        state.phase = "emergency_stop"
        state.energy_level = 0.0
        self.knowledge.save_state(state)
        self.interface.receive(
            human_input(
                "performance.runner",
                {
                    "action": "emergency_stop",
                    "text": "Emergency stop triggered",
                    "mute_all": True,
                    "approved": True,
                },
                priority=Priority.CRITICAL,
                tags=["override", "emergency"],
            )
        )

    def pause(self):
        """Pause the performance."""
        self._paused = True
        self.interface.receive(
            human_input(
                "performance.runner",
                {
                    "action": "pause",
                    "text": "Performance paused",
                    "mute_all": True,
                    "approved": True,
                },
                priority=Priority.HIGH,
                tags=["override", "pause"],
            )
        )

    def resume(self):
        """Resume the performance after a pause."""
        self._paused = False
        self._phase_start = datetime.now().timestamp()
        self.interface.receive(
            human_input(
                "performance.runner",
                {
                    "action": "resume",
                    "text": f"Resuming {self.config.phase.value}",
                    "approved": True,
                },
                priority=Priority.HIGH,
                tags=["override", "resume"],
            )
        )

    def end(self):
        """Gracefully end the performance and enter outro."""
        if self.config.phase != Phase.OUTRO and Phase.OUTRO in self.phase_configs:
            self.transition_to(Phase.OUTRO)
        self._running = False
        self._paused = False
        state = self.knowledge.load_state()
        state.phase = Phase.OUTRO.value
        self.knowledge.save_state(state)
        self._emit_control_event(
            "performance_end",
            {"name": self.config.name, "duration_seconds": round(self.performance_runtime(), 2)},
        )

    def handle_operator_message(self, message: UniversalMessage):
        """Handle live human overrides from CLI, keyboard, or dashboard."""
        action = message.payload.get("action")
        if action == "emergency_stop":
            self.emergency_stop()
        elif action in {"pause", "mute_all", "mute_toggle"}:
            self.pause()
        elif action == "resume":
            self.resume()
        elif action in {"transition", "next_phase"}:
            if action == "next_phase":
                phases = list(self.phase_configs)
                current_index = phases.index(self.config.phase)
                target_phase = phases[(current_index + 1) % len(phases)]
            else:
                target_phase = Phase(str(message.payload.get("phase", "")).lower())
            self.transition_to(target_phase)
        elif action == "set_energy":
            state = self.knowledge.load_state()
            state.energy_level = max(0.0, min(1.0, float(message.payload.get("target_energy", state.energy_level))))
            self.knowledge.save_state(state)

    @property
    def is_running(self) -> bool:
        """Return whether the performance is active."""
        return self._running

    @property
    def is_paused(self) -> bool:
        """Return whether the performance is paused."""
        return self._paused

    @property
    def phase_elapsed(self) -> float:
        """Seconds elapsed in the current phase."""
        if self._phase_start is None:
            return 0.0
        return datetime.now().timestamp() - self._phase_start

    def phase_runtime(self) -> float:
        """Compatibility wrapper for dashboard and CLI."""
        return self.phase_elapsed

    def performance_runtime(self) -> float:
        """Total seconds since the show started."""
        if self._started_at is None:
            return 0.0
        return datetime.now().timestamp() - self._started_at

    def visible_outputs(self) -> Iterable[str]:
        """Return outputs currently allowed for the active phase."""
        return self.phase_configs.get(self.config.phase, self.config).allowed_outputs

    def _apply_config(self, config: PerformanceConfig, reset_timer: bool = False):
        state = self.knowledge.load_state()
        state.name = config.name
        state.phase = config.phase.value
        state.energy_level = max(0.0, min(1.0, config.target_energy))
        state.constraints["allowed_outputs"] = list(config.allowed_outputs)
        state.constraints["human_override_priority"] = config.human_override_priority
        state.constraints["transition_min_duration"] = config.transition_min_duration
        self.knowledge.save_state(state)
        self.config = config
        if reset_timer:
            self._phase_start = datetime.now().timestamp()
        self.timeline.append(
            {
                "timestamp": datetime.now().timestamp(),
                "phase": config.phase.value,
                "target_energy": config.target_energy,
                "allowed_outputs": list(config.allowed_outputs),
            }
        )

    def _emit_control_event(self, event_name: str, payload: dict):
        self.interface.receive(
            UniversalMessage(
                type=MessageType.SYSTEM,
                source="performance.runner",
                payload={"event": event_name, **payload},
            )
        )
