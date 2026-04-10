"""DimensionDriver — maps sensor/adapter events to PhaseSpace dimension values.

The DimensionDriver bridges the sensor layer (motion, audio, occupancy, MIDI, keyboard)
and the PhaseSpace layer. It translates raw events into dimension value changes,
optionally with a smoothing filter (exponential moving average) to avoid jitter.

Example:
    driver = DimensionDriver(space)

    # Map Zigbee PIR → energy dimension
    driver.map("zigbee.front_pir", "occupancy",
               to_dimension="occupancy",
               scale=1.0, smoothing=0.3)

    # Map audio amplitude → energy dimension
    driver.map("audio.amplitude", "level",
               to_dimension="energy",
               scale=0.8, offset=0.1, smoothing=0.5)

    # Map QLab cue state → tension dimension
    driver.map("qlab", "cue_active",
               to_dimension="tension",
               scale=1.0, smoothing=0.2)

    driver.start()

    # In the run loop:
    # bus.subscribe("zigbee", driver.on_bus_event)
    # bus.subscribe("audio",  driver.on_bus_event)
    # space.tick(delta_seconds=0.1)  # advances dimension velocities
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
import time


# ------------------------------------------------------------------
# Mapping rules
# ------------------------------------------------------------------

@dataclass
class MappingRule:
    """A rule describing how a source signal maps to a dimension."""

    source_tag: str          # e.g. "zigbee.front_pir" or "audio.amplitude"
    source_key: str          # e.g. "occupancy" or "level" from the event payload
    dimension: str           # PhaseSpace dimension name
    scale: float = 1.0       # multiplicative scale
    offset: float = 0.0      # additive offset after scaling
    smoothing: float = 0.0   # EMA coefficient (0.0 = no smoothing, 1.0 = full smoothing)
    active: bool = True

    def apply(self, raw_value: float) -> float:
        """Transform a raw sensor value into a dimension value."""
        return max(0.0, min(1.0, raw_value * self.scale + self.offset))


@dataclass
class DimensionState:
    """Runtime state for a single dimension (includes EMA state)."""

    current: float = 0.0   # smoothed value
    raw: float = 0.0        # most recent raw value


# ------------------------------------------------------------------
# DimensionDriver
# ------------------------------------------------------------------

class DimensionDriver:
    """Maps sensor and adapter events to PhaseSpace dimension values.

    Subscribe the driver's `on_bus_event` to the message bus, or call
    `push` directly. The driver routes each event to any matching MappingRule,
    applies the scale/offset/smoothing transform, and updates the dimension.
    """

    def __init__(self, space):
        self.space = space
        self.rules: list[MappingRule] = []
        self._states: dict[str, DimensionState] = {}   # keyed by source_tag
        self._running = False
        self._transition_log: list[dict] = field(default_factory=list)

    # ---- Rule management -----------------------------------------

    def map(
        self,
        source_tag: str,
        source_key: str,
        to_dimension: str,
        scale: float = 1.0,
        offset: float = 0.0,
        smoothing: float = 0.0,
    ) -> MappingRule:
        """Register a mapping from a source signal to a dimension.

        source_tag:  bus message tag identifying the source (e.g. "zigbee.front_pir")
        source_key:  key in the message payload to read (e.g. "occupancy")
        to_dimension: PhaseSpace dimension to write
        scale:       multiply raw value by this
        offset:      add this after scaling
        smoothing:   EMA coefficient (0.0 = raw, 1.0 = full EMA)
        """
        rule = MappingRule(
            source_tag=source_tag,
            source_key=source_key,
            dimension=to_dimension,
            scale=scale,
            offset=offset,
            smoothing=smoothing,
        )
        self.rules.append(rule)
        self._states[source_tag] = DimensionState()
        return rule

    def unmap(self, source_tag: str) -> None:
        """Remove all rules originating from a given source tag."""
        self.rules = [r for r in self.rules if r.source_tag != source_tag]

    def enable(self, source_tag: str) -> None:
        for r in self.rules:
            if r.source_tag == source_tag:
                r.active = True

    def disable(self, source_tag: str) -> None:
        for r in self.rules:
            if r.source_tag == source_tag:
                r.active = False

    # ---- Event ingestion ----------------------------------------

    def on_bus_event(self, message) -> None:
        """Handle incoming bus messages — route to matching rules.

        message is any object with `.tags` (list of str) and `.payload` (dict).
        """
        tags = getattr(message, "tags", [])
        payload = getattr(message, "payload", {})

        for rule in self.rules:
            if not rule.active:
                continue
            # Check if any of the message tags match the source tag
            if rule.source_tag in tags:
                self._apply_rule(rule, payload)

    def push(self, source_tag: str, source_key: str, raw_value: float) -> None:
        """Direct push of a raw value — bypasses the bus.

        Use this for adapter callbacks or any internal signal source.
        """
        for rule in self.rules:
            if rule.source_tag == source_tag and rule.source_key == source_key and rule.active:
                self._apply_rule(rule, {"value": raw_value})

    def _apply_rule(self, rule: MappingRule, payload: dict) -> None:
        """Apply a single mapping rule to a payload value."""
        raw = payload.get(rule.source_key, payload.get("value", 0.0))
        if not isinstance(raw, (int, float)):
            return

        # EMA smoothing
        state = self._states.get(rule.source_tag, DimensionState())
        if rule.smoothing > 0.0:
            smoothed = state.current + rule.smoothing * (raw - state.current)
        else:
            smoothed = raw

        state.raw = raw
        state.current = smoothed
        self._states[rule.source_tag] = state

        # Write to PhaseSpace
        dim_value = rule.apply(smoothed)
        self.space.set(rule.dimension, dim_value)

    # ---- Status -------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return current driver state for debugging."""
        return {
            "active_rules": len([r for r in self.rules if r.active]),
            "total_rules": len(self.rules),
            "sources": list(self._states.keys()),
            "raw_values": {k: v.raw for k, v in self._states.items()},
            "smoothed": {k: round(v.current, 3) for k, v in self._states.items()},
            "dimension_snapshot": self.space.snapshot(),
        }
