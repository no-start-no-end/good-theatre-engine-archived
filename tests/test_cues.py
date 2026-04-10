"""Tests for cue list system."""
from __future__ import annotations

import pytest
from src.cues import Cue, CueList, CueType


class TestCueList:
    def test_add_and_get(self):
        cues = CueList("Test Show")
        cues.add_go(1, "House open", {"lights": {"fade": 1}}, ["open"])
        cues.add_go(5, "Opening moment", {"lights": {"fade": 1}, "audio": {"volume": 0.8}}, ["clap"])
        cues.add_go(10, "Fade to black", {"lights": {"fade": 0}}, ["close"])

        assert cues.get(1).description == "House open"
        assert cues.get(5).description == "Opening moment"
        assert cues.get(99) is None

    def test_next_after(self):
        cues = CueList()
        cues.add_go(1, "A", {})
        cues.add_go(5, "B", {})
        cues.add_go(10, "C", {})

        assert cues.next_after(1).number == 5
        assert cues.next_after(5).number == 10
        assert cues.next_after(10) is None

    def test_fire_and_pending(self):
        cues = CueList()
        cues.add_go(1, "One", {})
        cues.add_go(2, "Two", {})
        cues.add_go(3, "Three", {})

        assert len(cues.pending()) == 3
        cues.fire(2)
        assert cues.is_fired(2)
        assert not cues.is_fired(1)
        assert len(cues.pending()) == 2

    def test_reset(self):
        cues = CueList()
        cues.add_go(1, "One", {})
        cues.fire(1)
        assert cues.is_fired(1)
        cues.reset()
        assert not cues.is_fired(1)

    def test_timeline_seconds(self):
        cues = CueList()
        cues.add(Cue(number=1, description="a", offset_seconds=0.0, pre_wait=0.0, fade_duration=2.0))
        cues.add(Cue(number=2, description="b", offset_seconds=5.0, pre_wait=1.0, fade_duration=3.0))
        # max offset + pre_wait + fade = 5 + 1 + 3 = 9.0
        assert cues.timeline_seconds() == 9.0

    def test_to_dict(self):
        cues = CueList("My Show")
        cues.add_go(1, "Test", {"target": "lights"}, ["tag1"])
        d = cues.to_dict()
        assert d["name"] == "My Show"
        assert d["cue_count"] == 1
        assert d["fired_count"] == 0
        assert len(d["cues"]) == 1
        assert d["cues"][0]["number"] == 1
