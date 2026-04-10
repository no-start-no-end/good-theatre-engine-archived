"""Phase space matrix for theatre performance orchestration.

Instead of a linear phase sequence (INTRO → ACT_1 → ...), the performance
is modeled as a multi-dimensional continuous space. Each phase occupies a
region defined by boundary ranges on every dimension.

Transitions happen two ways:
  Push  — dimension values cross a boundary naturally → phase shifts auto
  Jump  — explicit call → go to any phase immediately

Dimensions are continuous signals (energy, tempo, color_temp, audio level,
motion intensity, etc.). The engine tracks them in real-time and can detect
when the system state vector enters a new phase region.

Example:
    space = PhaseSpace()
    space.add_dimension("energy", current=0.2, min=0.0, max=1.0)
    space.add_dimension("tempo",  current=60,   min=20, max=140)
    space.add_dimension("color_temp", current=3000, min=153, max=6535)

    space.add_region("intro", {
        "energy":      (0.00, 0.30),
        "tempo":       (40,   70),
        "color_temp":  (2000, 3200),
    })
    space.add_region("act_1", {
        "energy":      (0.30, 0.65),
        "tempo":       (70,   100),
        "color_temp":  (3200, 4800),
    })

    space.on_enter("act_1", lambda: print("Entering Act 1!"))
    space.set("energy", 0.5)   # push → may trigger act_1
    space.jump("intermission") # explicit jump
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
import time


# ------------------------------------------------------------------
# Dimension
# ------------------------------------------------------------------

@dataclass
class Dimension:
    """A single continuous axis in the phase space."""

    name: str
    current: float
    min: float
    max: float
    velocity: float = 0.0  # rate of change per second (positive = increasing)

    def set(self, value: float) -> None:
        """Set the current value and compute velocity from the previous value."""
        prev = self.current
        self.current = max(self.min, min(self.max, value))

    def update(self, delta_seconds: float) -> None:
        """Advance the dimension by its velocity."""
        if self.velocity != 0.0:
            self.current = max(self.min, min(self.max, self.current + self.velocity * delta_seconds))


# ------------------------------------------------------------------
# PhaseRegion
# ------------------------------------------------------------------

# Type for a dimension boundary: (min, max) inclusive range
DimensionRange = tuple[float, float]


@dataclass
class PhaseRegion:
    """A named region in the phase space, defined by dimension ranges."""

    name: str
    boundaries: dict[str, DimensionRange]
    # Callback fired when the system state enters this region
    on_enter: Callable[["PhaseSpace"], None] | None = None
    # Callback fired when the system state leaves this region
    on_exit: Callable[["PhaseSpace"], None] | None = None


# ------------------------------------------------------------------
# PhaseSpace
# ------------------------------------------------------------------

class PhaseSpace:
    """Multi-dimensional phase space with push and jump transitions.

    The space tracks N continuous dimensions. Each phase/region occupies
    a hyper-rectangle defined by (min, max) ranges on each dimension.

    Two transition modes:
      push  — engine detects that current dimension values place the system
              inside a new region → automatic transition
      jump  — external call forces immediate transition to a named region
    """

    def __init__(self):
        self.dimensions: dict[str, Dimension] = {}
        self.regions: dict[str, PhaseRegion] = {}
        self._current_region: PhaseRegion | None = None
        self._last_update: float = field(default_factory=time.time)

    # ---- Dimension management -------------------------------------

    def add_dimension(self, name: str, current: float, min: float, max: float) -> None:
        """Add a continuous dimension to the space."""
        self.dimensions[name] = Dimension(name=name, current=current, min=min, max=max)

    def set(self, name: str, value: float) -> None:
        """Set a dimension's current value (triggers push detection)."""
        if name not in self.dimensions:
            raise KeyError(f"Unknown dimension: {name!r}")
        dim = self.dimensions[name]
        dim.set(value)

    def set_velocity(self, name: str, velocity: float) -> None:
        """Set a dimension's rate of change (used during tick)."""
        if name not in self.dimensions:
            raise KeyError(f"Unknown dimension: {name!r}")
        self.dimensions[name].velocity = velocity

    def get(self, name: str) -> float:
        """Get a dimension's current value."""
        return self.dimensions[name].current

    def snapshot(self) -> dict[str, float]:
        """Return all current dimension values."""
        return {n: d.current for n, d in self.dimensions.items()}

    # ---- Region management ----------------------------------------

    def add_region(self, name: str, boundaries: dict[str, DimensionRange]) -> None:
        """Add a named phase region with dimension boundary ranges."""
        self.regions[name] = PhaseRegion(name=name, boundaries=boundaries)

    def on_enter(self, region_name: str, callback: Callable[[PhaseSpace], None]) -> None:
        """Register a callback for when the system enters a region."""
        self.regions[region_name].on_enter = callback

    def on_exit(self, region_name: str, callback: Callable[[PhaseSpace], None]) -> None:
        """Register a callback for when the system leaves a region."""
        self.regions[region_name].on_exit = callback

    # ---- Transition detection --------------------------------------

    def _in_region(self, region: PhaseRegion) -> bool:
        """Check if the current dimension state is inside a region's boundaries."""
        for name, (lo, hi) in region.boundaries.items():
            if name not in self.dimensions:
                return False
            val = self.dimensions[name].current
            if val < lo or val > hi:
                return False
        return True

    def _detect_push(self) -> PhaseRegion | None:
        """Detect which region the current state vector is in (or None).

        When multiple regions match (overlapping boundaries), prefer the one
        with the smallest hypervolume (most constrained = most specific).
        This handles overlapping regions correctly — e.g. intermission (0.0-0.25)
        is a subset of intro (0.0-0.3); when energy=0.15, intermission wins.
        """
        candidates = [
            (self._region_volume(region), region)
            for region in self.regions.values()
            if self._in_region(region) and region is not self._current_region
        ]
        if not candidates:
            return None
        # Sort by volume ascending → smallest/most specific first
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def _region_volume(self, region: PhaseRegion) -> float:
        """Compute the hypervolume of a region (product of all dimension ranges).

        Regions with smaller volume are more constrained / specific.
        Used to break ties when multiple regions overlap.
        """
        volume = 1.0
        for name, (lo, hi) in region.boundaries.items():
            if name in self.dimensions:
                dim_range = self.dimensions[name].max - self.dimensions[name].min
                if dim_range > 0:
                    # Normalise range by the dimension's full range, then multiply
                    volume *= (hi - lo) / dim_range
        return volume

    def _push_to(self, region: PhaseRegion) -> None:
        """Execute transition into a region."""
        if self._current_region is not None:
            exit_cb = self._current_region.on_exit
            if exit_cb:
                exit_cb(self)
        self._current_region = region
        enter_cb = region.on_enter
        if enter_cb:
            enter_cb(self)

    # ---- Public transition API ------------------------------------

    def tick(self, delta_seconds: float | None = None) -> PhaseRegion | None:
        """Advance all dimensions by their velocities; detect and execute push transitions.

        Call this in the engine run loop (e.g. every 100ms).
        Returns the new region if a push transition occurred, else None.
        """
        if delta_seconds is None:
            now = time.time()
            delta_seconds = now - self._last_update
            self._last_update = now

        # Advance all dimensions
        for dim in self.dimensions.values():
            dim.update(delta_seconds)

        # Detect push
        target = self._detect_push()
        if target is not None:
            self._push_to(target)
            return target
        return None

    def jump(self, region_name: str) -> None:
        """Immediately jump to a named region (bypasses boundary detection)."""
        if region_name not in self.regions:
            raise KeyError(f"Unknown region: {region_name!r}")
        target = self.regions[region_name]
        if target is self._current_region:
            return  # already there
        self._push_to(target)

    def current_region(self) -> str | None:
        """Return the name of the currently active region."""
        return self._current_region.name if self._current_region else None

    def status(self) -> dict[str, Any]:
        """Return a snapshot of the phase space state."""
        return {
            "current_region": self.current_region(),
            "dimensions": {n: d.current for n, d in self.dimensions.items()},
            "regions": list(self.regions.keys()),
        }
