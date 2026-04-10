"""Tests for the OSC input adapter."""
from __future__ import annotations

import pytest
from src.adapters.inputs.osc import OSCInput


class TestOSCInput:
    def test_extract_cue_number(self):
        adapter = OSCInput()
        assert adapter._extract_cue_number("/cue/5/go") == 5
        assert adapter._extract_cue_number("/cue/12/stop") == 12
        assert adapter._extract_cue_number("/other/thing") is None

    def test_classify(self):
        adapter = OSCInput()
        assert adapter._classify("/cue/5/go", 5) == "cue_fire"
        assert adapter._classify("/cue/3/stop", 3) == "cue_stop"
        assert adapter._classify("/midi/note", None) == "midi_note"
        assert adapter._classify("/other/thing", None) == "raw_osc"

    def test_build_cue_message(self):
        adapter = OSCInput()
        msg = adapter._build_message("/cue/7/go", "cue_fire", 7, [])
        assert msg.type.value == "human_input"
        assert msg.payload["cue_number"] == 7
        assert msg.payload["osc_action"] == "fire"
        assert "cue_7" in msg.metadata.tags

    def test_build_midi_message(self):
        adapter = OSCInput()
        msg = adapter._build_message("/midi/note", "midi_note", None, [60, 96])
        assert msg.type.value == "human_input"
        assert msg.payload["note"] == 60
        assert msg.payload["velocity"] == 96

    def test_build_raw_message(self):
        adapter = OSCInput()
        msg = adapter._build_message("/custom/addr", "raw_osc", None, [1.0, 2.0])
        assert msg.type.value == "human_input"
        assert msg.payload["raw_address"] == "/custom/addr"
        assert msg.payload["args"] == [1.0, 2.0]
