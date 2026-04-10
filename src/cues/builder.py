"""Programmatic show config builder.

Provides a clean API for defining phases and cue lists without writing raw Python.

Example:
    from src.cues.builder import Show, Phase, Cue

    show = Show("My Piece") \\
        .phase("intro", energy=0.25, allowed=["lights", "audio", "display"]) \\
        .cue(1, "House up", lights={"channel": 1, "value": 0.4, "duration": 5.0}) \\
        .cue(2, "Sound on", audio={"cue_number": 1}) \\
        .phase("act_1", energy=0.6) \\
        .cue(5, "Spotlight", lights={"channel": 3, "value": 1.0})

    show.save("my_show.py")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..performance import PerformanceConfig, Phase
from . import Cue, CueList, CueType


@dataclass
class PhaseDef:
    phase: Phase
    target_energy: float
    allowed_outputs: list[str]
    transition_min_duration: float = 1.0
    cues: list[Cue] = field(default_factory=list)

    def to_config(self, name: str) -> PerformanceConfig:
        return PerformanceConfig(
            name=name,
            phase=self.phase,
            target_energy=self.target_energy,
            allowed_outputs=self.allowed_outputs,
            transition_min_duration=self.transition_min_duration,
        )


class Show:
    """Fluently build a full show config with phases and cue list."""

    def __init__(self, name: str):
        self.name = name
        self._phase_defs: dict[Phase, PhaseDef] = {}
        self._cue_list = CueList(name)
        self._current_phase: Phase | None = None
        self._next_cue_number = 1

    def phase(
        self,
        name: str,
        energy: float = 0.5,
        allowed: list[str] | None = None,
        min_duration: float = 1.0,
    ) -> "Show":
        """Define a phase. Returns self for chaining."""
        phase_enum = Phase(name.lower())
        self._phase_defs[phase_enum] = PhaseDef(
            phase=phase_enum,
            target_energy=energy,
            allowed_outputs=allowed or ["lights", "audio", "display"],
            transition_min_duration=min_duration,
        )
        self._current_phase = phase_enum
        return self

    def cue(
        self,
        number: int | None,
        description: str,
        targets: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        offset: float = 0.0,
    ) -> "Show":
        """Add a cue to the current phase (or the show if no phase open)."""
        if targets is None:
            targets = {}
        cue = Cue(
            number=number or self._next_cue_number,
            description=description,
            targets=targets,
            tags=tags or [],
            offset_seconds=offset,
        )
        self._cue_list.add(cue)
        if number and number >= self._next_cue_number:
            self._next_cue_number = number + 1
        else:
            self._next_cue_number += 1
        return self

    def go(
        self,
        description: str,
        targets: dict[str, Any],
        tags: list[str] | None = None,
    ) -> "Show":
        """Add a cue using auto-incremented cue number."""
        return self.cue(None, description, targets, tags)

    def to_config_dict(self) -> dict[str, Any]:
        """Return the full config dict suitable for writing to a .py file."""
        phases_code = []
        for phase, def_ in sorted(self._phase_defs.items(), key=lambda x: x[0].value):
            phases_code.append(f"""    Phase.{phase.name.upper()}: PerformanceConfig(
        name=PERFORMANCE_NAME,
        phase=Phase.{phase.name.upper()},
        target_energy={def_.target_energy},
        allowed_outputs={def_.allowed_outputs!r},
        transition_min_duration={def_.transition_min_duration},
    ),""")

        cue_code = []
        for c in self._cue_list.all():
            targets_repr = ",".join(f"'{k}': {v!r}" for k, v in c.targets.items())
            cue_code.append(f"""    ({c.number}, "{c.description}", {{{targets_repr}}}, {c.tags!r}),""")

        return {
            "name": self.name,
            "phase_defs": self._phase_defs,
            "cue_list": self._cue_list,
            "code_template": f'''
from src.performance import PerformanceConfig, Phase
from src.cues import CueList, CueType

PERFORMANCE_NAME = {self.name!r}

PHASES = {{
{chr(10).join(phases_code)}
}}

CUE_LIST = CueList({self.name!r})
CUE_LIST._cues = [
{chr(10).join(f"    Cue({c[0]}, {c[1]!r}, targets={{{c[2]}}}, tags={c[3]})" for c in [x for x in [tuple(x) for x in cue_code]])}
]
''',
        }

    def save(self, path: str):
        """Write the show config as a runnable Python file."""
        from pathlib import Path
        config = self.to_config_dict()
        Path(path).write_text(config["code_template"])

    def build(self) -> tuple[PerformanceConfig, dict[Phase, PerformanceConfig], CueList]:
        """Return (first_config, phase_configs, cue_list) for passing to PerformanceRunner."""
        if not self._phase_defs:
            raise ValueError("Show must have at least one phase")
        phase_configs = {p.to_config(self.name): p for p in self._phase_defs.values()}
        first = phase_configs[Phase.INTRO] if Phase.INTRO in phase_configs else next(iter(phase_configs))
        return first, phase_configs, self._cue_list
