"""Performance config format supporting both phases and cue lists."""
from __future__ import annotations

from src.performance import PerformanceConfig, Phase
from src.cues import CueList, CueType


PERFORMANCE_NAME = "Good Theatre Performance"

# Phase definitions
PHASES = {
    Phase.INTRO: PerformanceConfig(
        name=PERFORMANCE_NAME,
        phase=Phase.INTRO,
        target_energy=0.3,
        allowed_outputs=["lights", "audio", "display"],
        transition_min_duration=1.0,
    ),
    Phase.ACT_1: PerformanceConfig(
        name=PERFORMANCE_NAME,
        phase=Phase.ACT_1,
        target_energy=0.55,
        allowed_outputs=["lights", "audio", "display"],
        transition_min_duration=1.0,
    ),
    Phase.INTERMISSION: PerformanceConfig(
        name=PERFORMANCE_NAME,
        phase=Phase.INTERMISSION,
        target_energy=0.2,
        allowed_outputs=["lights", "display"],
        transition_min_duration=1.0,
    ),
    Phase.ACT_2: PerformanceConfig(
        name=PERFORMANCE_NAME,
        phase=Phase.ACT_2,
        target_energy=0.82,
        allowed_outputs=["lights", "audio", "display"],
        transition_min_duration=1.0,
    ),
    Phase.OUTRO: PerformanceConfig(
        name=PERFORMANCE_NAME,
        phase=Phase.OUTRO,
        target_energy=0.1,
        allowed_outputs=["lights", "display"],
        transition_min_duration=1.0,
    ),
}

# Optional cue list — set to None if no cue list needed
CUE_LIST: CueList | None = None
