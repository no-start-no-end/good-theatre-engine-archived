"""Tests for the replay console."""
from __future__ import annotations

import json
import pytest
from src.replay import ReplayConsole


@pytest.fixture
def sample_events():
    return [
        {
            "logged_at": "2026-04-09T10:00:00",
            "trace_id": "abc12340",
            "message": {
                "type": "sensor_event",
                "source": "mock_motion",
                "payload": {"zone": "stage", "level": 0.8},
            },
        },
        {
            "logged_at": "2026-04-09T10:00:01",
            "trace_id": "abc12341",
            "message": {
                "type": "output_command",
                "source": "engine.lights",
                "payload": {"cue": 1, "action": "on"},
            },
        },
        {
            "logged_at": "2026-04-09T10:00:02",
            "trace_id": "abc12342",
            "message": {
                "type": "human_input",
                "source": "keyboard.op_1",
                "payload": {"text": "GO"},
            },
        },
    ]


class TestReplayConsole:
    def test_init_loads_events(self, sample_events):
        console = ReplayConsole(sample_events)
        assert len(console.events) == 3
        assert console.index == 0

    def test_step_moves_forward(self, sample_events):
        console = ReplayConsole(sample_events)
        console.cmd_step(["1"])
        assert console.index == 1
        console.cmd_step(["1"])
        assert console.index == 2

    def test_step_clamped_at_end(self, sample_events):
        console = ReplayConsole(sample_events)
        console.index = 2
        console.cmd_step(["10"])
        assert console.index == 2  # clamped

    def test_back_moves_backward(self, sample_events):
        console = ReplayConsole(sample_events)
        console.index = 2
        console.cmd_back(["1"])
        assert console.index == 1

    def test_back_clamped_at_start(self, sample_events):
        console = ReplayConsole(sample_events)
        console.cmd_back(["10"])
        assert console.index == 0

    def test_goto_jumps_to_index(self, sample_events):
        console = ReplayConsole(sample_events)
        console.cmd_goto(["2"])
        assert console.index == 2

    def test_goto_clamped(self, sample_events):
        console = ReplayConsole(sample_events)
        console.cmd_goto(["999"])
        assert console.index == 2
        console.cmd_goto(["-1"])
        assert console.index == 0

    def test_filter_by_type(self, sample_events):
        console = ReplayConsole(sample_events)
        console.cmd_filter(["sensor_event"])
        assert len(console.filtered) == 1
        assert console.filtered[0] == 0

    def test_filter_by_source(self, sample_events):
        console = ReplayConsole(sample_events)
        console.cmd_filter(["_", "keyboard"])
        assert len(console.filtered) == 1
        assert console.filtered[0] == 2

    def test_filter_combined(self, sample_events):
        console = ReplayConsole(sample_events)
        console.cmd_filter(["sensor_event", "mock"])
        assert len(console.filtered) == 1
        assert console.filtered[0] == 0

    def test_filter_none_resets(self, sample_events):
        console = ReplayConsole(sample_events)
        console.filtered = [0]
        console.cmd_filter(["_"])
        assert console.filter_type is None
        assert console.filter_source is None

    def test_tag_annotates_event(self, sample_events):
        console = ReplayConsole(sample_events)
        console.index = 0
        console.cmd_tag(["important", "check this"])
        assert console.annotations[0] == "important check this"

    def test_info_shows_stats(self, sample_events, capsys):
        console = ReplayConsole(sample_events)
        console.cmd_info([])
        out = capsys.readouterr().out
        assert "Total events: 3" in out
        assert "sensor_event" in out

    def test_show_context(self, sample_events, capsys):
        console = ReplayConsole(sample_events)
        console.index = 1
        console.cmd_show(["1"])
        out = capsys.readouterr().out
        assert ">>>" in out  # current marker

    def test_save_annotated(self, sample_events, tmp_path):
        console = ReplayConsole(sample_events)
        console.cmd_tag(["test annotation"])
        path = tmp_path / "ann.json"
        console.cmd_save([str(path)])
        assert path.exists()
        data = json.loads(path.read_text())
        assert len(data) == 1
        assert data[0]["annotation"] == "test annotation"

    def test_empty_console(self):
        console = ReplayConsole([])
        assert len(console.events) == 0
        assert len(console.filtered) == 0
