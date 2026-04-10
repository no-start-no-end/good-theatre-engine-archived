"""Default performance config with example cue list."""
from __future__ import annotations

from src.performance import PerformanceConfig, Phase
from src.cues import CueList


PERFORMANCE_NAME = "Good Theatre — First Performance"


PHASES = {
    Phase.INTRO: PerformanceConfig(
        name=PERFORMANCE_NAME,
        phase=Phase.INTRO,
        target_energy=0.25,
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


def _build_cue_list() -> CueList:
    from src.cues import Cue

    cues = CueList(PERFORMANCE_NAME)
    cues.add_go(1, "House open — lights fade in", {"lights": {"channel": 1, "action": "fade", "value": 0.4, "duration": 5.0}}, ["open", "lights"])
    cues.add_go(2, "Ambient drone begins", {"audio": {"cue_number": 1, "midi_action": "go"}}, ["audio", "ambient"])
    cues.add_go(3, "Motion on stage — lights follow", {"lights": {"channel": 3, "action": "fade", "value": 0.8, "duration": 1.5}}, ["stage", "lights"])
    cues.add_go(4, "Text: 'The room is listening'", {"display": {"text": "The room is listening", "style": "calm"}}, ["display"])
    cues.add_go(5, "Red wash — tension rising", {"lights": {"channel": 5, "action": "fade", "value": 0.9, "duration": 2.0}}, ["tension", "lights"])
    cues.add_go(6, "Audio stop — silence", {"audio": {"action": "stop", "cue": 1}}, ["audio", "pause"])
    cues.add_go(7, "Blackout", {"lights": {"action": "blackout"}}, ["blackout", "lights"])
    cues.add_go(8, "Single spotlight", {"lights": {"channel": 7, "action": "fade", "value": 1.0, "duration": 0.5}}, ["spotlight", "lights"])
    cues.add_go(9, "Text: 'What do you hear?'", {"display": {"text": "What do you hear?", "style": "alert"}}, ["display", "final"])
    cues.add_go(10, "End — fade to black", {"lights": {"action": "fade", "channel": 7, "value": 0.0, "duration": 4.0}}, ["end"])
    return cues


CUE_LIST = _build_cue_list()
