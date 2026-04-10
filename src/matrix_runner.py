"""MatrixRunner — PhaseSpace orchestrator backed by PerformanceRunner state.

MatrixRunner runs the phase space matrix as the primary performance driver,
with PerformanceRunner handling canonical state, knowledge persistence, and
the constraint model (allowed outputs, human override priority).

Two modes:
  matrix_first  — PhaseSpace drives all transitions; PerformanceRunner follows
  sequence_first — PerformanceRunner drives (linear sequence); PhaseSpace monitors

The default is matrix_first.

Example:
    # Define the space
    space = PhaseSpace()
    space.add_dimension("energy",     current=0.2, min=0.0, max=1.0)
    space.add_dimension("tempo",      current=60,  min=20, max=140)
    space.add_dimension("color_temp", current=3200, min=153, max=6535)

    space.add_region("detecting", {
        "energy": (0.00, 0.30), "tempo": (40, 70), "color_temp": (2000, 3200),
    })
    space.add_region("stabilizing", {
        "energy": (0.30, 0.65), "tempo": (70, 100), "color_temp": (3200, 4800),
    })
    space.add_region("suspended", {
        "energy": (0.00, 0.25), "tempo": (30, 55), "color_temp": (2400, 3000),
    })
    space.add_region("escalating", {
        "energy": (0.55, 1.00), "tempo": (90, 140), "color_temp": (4500, 6500),
    })
    space.add_region("dispersing", {
        "energy": (0.00, 0.15), "tempo": (20, 40), "color_temp": (2000, 2700),
    })

    # Build runner
    runner = MatrixRunner(
        space=space,
        knowledge=knowledge,
        interface=interface,
        decision_engine=decision_engine,
        dimension_driver=driver,
    )

    # Register what happens on each phase transition
    runner.on_phase_enter("act_1", lambda: lights.go("act_1_preset"))
    runner.on_phase_enter("act_2", lambda: audio.go_cue(7))

    runner.start()

    # In run loop:
    while runner.is_running:
        runner.tick()
        time.sleep(0.1)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable
import threading
import time

from .core.interface import InterfaceLayer
from .core.knowledge import KnowledgeBase
from .core.message import MessageType, Priority, UniversalMessage, human_input
from .ai.decision import DecisionEngine
from .performance import Phase, PerformanceConfig, PerformanceRunner
from .performance_matrix import PhaseSpace, PhaseRegion


class Mode(Enum):
    MATRIX_FIRST = "matrix_first"    # PhaseSpace drives; PerformanceRunner follows
    SEQUENCE_FIRST = "sequence_first"  # PerformanceRunner drives; PhaseSpace monitors


@dataclass
class PhaseTransition:
    timestamp: str
    from_region: str | None
    to_region: str
    trigger: str  # "push" | "jump" | "manual" | "operator"


class MatrixRunner:
    """Orchestrates PhaseSpace + PerformanceRunner as a unified performance engine.

    MatrixRunner wires the phase space matrix into the engine's run loop.
    It owns the PhaseSpace (dimensions, regions, push detection) and the
    PerformanceRunner (canonical phase state, knowledge, constraints).

    Two modes:
      MATRIX_FIRST   — push/jump transitions from PhaseSpace drive PerformanceRunner
      SEQUENCE_FIRST — PerformanceRunner's linear phase sequence is primary;
                       PhaseSpace is updated to follow but does not drive
    """

    def __init__(
        self,
        space: PhaseSpace,
        knowledge: KnowledgeBase,
        interface: InterfaceLayer,
        decision_engine: DecisionEngine,
        dimension_driver: Any | None = None,  # DimensionDriver
        phase_configs: dict[Phase, PerformanceConfig] | None = None,
        mode: Mode = Mode.MATRIX_FIRST,
    ):
        self.space = space
        self.knowledge = knowledge
        self.interface = interface
        self.decision_engine = decision_engine
        self.dimension_driver = dimension_driver
        self.mode = mode

        # Derive initial PerformanceConfig from the space's starting region
        initial_phase, initial_config = self._derive_phase_config(space.current_region())
        self._perf_runner = PerformanceRunner(
            config=initial_config,
            knowledge=knowledge,
            interface=interface,
            decision_engine=decision_engine,
            phase_configs=phase_configs or {},
        )

        # Phase callbacks — user-registered enter/exit hooks
        self._on_enter: dict[str, list[Callable[[PhaseSpace], None]]] = {}
        self._on_exit: dict[str, list[Callable[[PhaseSpace], None]]] = {}

        self._running = False
        self._thread: threading.Thread | None = None
        self._last_tick: float = time.time()
        self._transition_log: list[PhaseTransition] = []

        # Wire PhaseSpace callbacks to MatrixRunner handlers
        for region_name in space.regions:
            region = space.regions[region_name]
            region.on_enter = self._make_enter_handler(region_name)
            region.on_exit = self._make_exit_handler(region_name)

    # ---- Phase ↔ Region mapping ----------------------------------

    PHASE_FROM_REGION: dict[str, Phase] = {
        "detecting":    Phase.INTRO,
        "stabilizing":  Phase.ACT_1,
        "suspended":    Phase.INTERMISSION,
        "escalating":   Phase.ACT_2,
        "dispersing":   Phase.OUTRO,
    }

    REGION_FROM_PHASE: dict[Phase, str] = {v: k for k, v in PHASE_FROM_REGION.items()}

    def _derive_phase_config(self, region_name: str | None) -> tuple[Phase, PerformanceConfig]:
        """Derive the initial Phase and PerformanceConfig from a region name."""
        if region_name:
            phase = self.PHASE_FROM_REGION.get(region_name, Phase.INTRO)
        else:
            phase = Phase.INTRO
        config = PerformanceConfig(
            name="Matrix Performance",
            phase=phase,
            target_energy=0.5,
        )
        return phase, config

    def _make_enter_handler(self, region_name: str):
        # Enter callbacks are no-ops here — tick() handles all transition detection
        def handler(space: PhaseSpace):
            pass
        return handler

    def _make_exit_handler(self, region_name: str):
        def handler(space: PhaseSpace):
            pass
        return handler

    def _handle_transition(self, to_region: str, trigger: str) -> None:
        """Handle a phase/region transition from either push, jump, or manual."""
        prev_region = self._transition_log[-1].to_region if self._transition_log else None
        entry = PhaseTransition(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            from_region=prev_region,
            to_region=to_region,
            trigger=trigger,
        )
        self._transition_log.append(entry)

        phase = self.PHASE_FROM_REGION.get(to_region)
        if phase:
            self._perf_runner.transition_to(phase)

        # Fire user-registered callbacks
        callbacks = self._on_enter.get(to_region, [])
        for cb in callbacks:
            cb(self.space)

        self._emit_event("phase_enter", to_region, trigger)

    # ---- Public API: callbacks ----------------------------------

    def on_phase_enter(self, region_name: str, callback: Callable[[PhaseSpace], None]) -> None:
        """Register a callback for when a region is entered."""
        self._on_enter.setdefault(region_name, []).append(callback)

    def on_phase_exit(self, region_name: str, callback: Callable[[PhaseSpace], None]) -> None:
        """Register a callback for when a region is exited."""
        self._on_exit.setdefault(region_name, []).append(callback)

    # ---- Lifecycle ----------------------------------------------

    def start(self) -> None:
        """Start the matrix runner in a background thread."""
        if self._running:
            return
        self._running = True
        self._last_tick = time.time()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._emit_event("matrix_start", self.space.current_region() or "none", "start")

    def _run_loop(self) -> None:
        """Background loop: tick PhaseSpace and detect push transitions."""
        while self._running:
            self.tick()
            time.sleep(0.1)  # 10 Hz tick rate

    def stop(self) -> None:
        """Stop the matrix runner."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        self._emit_event("matrix_stop", self.space.current_region() or "none", "stop")

    def tick(self, delta_seconds: float | None = None) -> PhaseRegion | None:
        """Tick the PhaseSpace and detect push transitions.

        Call this in the run loop (or let the background thread handle it).
        Returns the new region if a push transition fired, else None.
        """
        if delta_seconds is None:
            now = time.time()
            delta_seconds = now - self._last_tick
            self._last_tick = now

        if self.mode == Mode.MATRIX_FIRST:
            new_region = self.space.tick(delta_seconds=delta_seconds)
            if new_region is not None:
                self._handle_transition(new_region.name, "push")
            return new_region
        else:
            # Sequence-first: keep space in sync with PerformanceRunner's phase
            self._sync_space_from_perf()
            return None

    def _sync_space_from_perf(self) -> None:
        """Update PhaseSpace to reflect PerformanceRunner's current phase."""
        region_name = self.REGION_FROM_PHASE.get(self._perf_runner.config.phase)
        if region_name and self.space.current_region() != region_name:
            self.space.jump(region_name)

    # ---- Jump / manual transitions ------------------------------

    def jump(self, region_name: str) -> None:
        """Immediately jump to a named region (operator override, explicit)."""
        if self.space.current_region() == region_name:
            return  # already there — no-op
        self.space.jump(region_name)
        self._handle_transition(region_name, "jump")

    def operator_override(self, region_name: str) -> None:
        """Human operator jumped to a region — highest priority."""
        self._handle_transition(region_name, "operator")

    # ---- Properties ---------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_region(self) -> str | None:
        return self.space.current_region()

    @property
    def current_phase(self) -> Phase:
        return self._perf_runner.config.phase

    @property
    def performance_runner(self) -> PerformanceRunner:
        """Direct access to the underlying PerformanceRunner."""
        return self._perf_runner

    # ---- Status -------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Full snapshot of the matrix runner state."""
        return {
            "mode": self.mode.value,
            "running": self._running,
            "current_region": self.current_region,
            "current_phase": self.current_phase.value,
            "space": self.space.status(),
            "perf": {
                "phase": self._perf_runner.config.phase.value,
                "energy": self._perf_runner.config.target_energy,
                "allowed_outputs": self._perf_runner.config.allowed_outputs,
            },
            "transitions": [
                {"from": t.from_region, "to": t.to_region, "trigger": t.trigger, "ts": t.timestamp}
                for t in self._transition_log[-10:]
            ],
        }

    def _emit_event(self, event: str, region: str, trigger: str) -> None:
        """Emit a control event to the interface."""
        self.interface.receive(
            UniversalMessage(
                type=MessageType.SYSTEM,
                source="matrix.runner",
                payload={"event": event, "region": region, "trigger": trigger},
            )
        )
