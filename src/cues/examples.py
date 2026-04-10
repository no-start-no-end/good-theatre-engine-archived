"""Example cue list for a short atmospheric theatre piece."""
from __future__ import annotations

from . import Cue, CueList, CueType


def build_example_cue_list() -> CueList:
    """A 10-cue atmospheric opening piece."""
    cues = CueList("Atmospheric Opening")

    # Cue 1 — House open: lights up slowly
    cues.add_go(
        1,
        "House open — lights fade in",
        {"lights": {"channel": 1, "action": "fade", "value": 0.4, "duration": 5.0}},
        tags=["open", "lights"],
    )

    # Cue 2 — Ambient sound enters
    cues.add_go(
        2,
        "Ambient drone begins",
        {"audio": {"cue_number": 1, "midi_action": "go"}},
        tags=["audio", "ambient"],
    )

    # Cue 3 — First movement detected
    cues.add_go(
        3,
        "Motion on stage — lights follow",
        {"lights": {"channel": 3, "action": "fade", "value": 0.8, "duration": 1.5}},
        tags=["stage", "lights"],
    )

    # Cue 4 — Display text moment
    cues.add_go(
        4,
        "Text: 'The room is listening'",
        {"display": {"text": "The room is listening", "style": "calm"}},
        tags=["display"],
    )

    # Cue 5 — Tension build: red light pulse
    cues.add_go(
        5,
        "Red wash — tension rising",
        {"lights": {"channel": 5, "action": "fade", "value": 0.9, "duration": 2.0}},
        tags=["tension", "lights"],
    )

    # Cue 6 — Sudden silence
    cues.add_go(
        6,
        "Audio stop — moment of silence",
        {"audio": {"action": "stop", "cue": 1}},
        tags=["audio", "pause"],
    )

    # Cue 7 — Darkness
    cues.add_go(
        7,
        "Blackout",
        {"lights": {"action": "blackout"}},
        tags=["blackout", "lights"],
    )

    # Cue 8 — Spotlight from above
    cues.add_go(
        8,
        "Single spotlight",
        {"lights": {"channel": 7, "action": "fade", "value": 1.0, "duration": 0.5}},
        tags=["spotlight", "lights"],
    )

    # Cue 9 — Final display text
    cues.add_go(
        9,
        "Text: 'What do you hear?'",
        {"display": {"text": "What do you hear?", "style": "alert"}},
        tags=["display", "final"],
    )

    # Cue 10 — Fade out and end
    cues.add_go(
        10,
        "End — fade to black",
        {
            "lights": {"action": "fade", "channel": 7, "value": 0.0, "duration": 4.0}},
        tags=["end"],
    )

    return cues
