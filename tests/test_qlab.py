"""Tests for QLab integration."""
from __future__ import annotations

import pytest
from src.qlab import QLabSender, QLabWatcher


class TestQLabSender:
    def test_build_osc_packet(self):
        sender = QLabSender()
        # Test basic cue fire packet builds without error
        packet = sender._build_osc("/cue/5/go", [])
        assert packet.startswith(b"/cue/5/go")
        assert len(packet) > 8

    def test_build_osc_with_args(self):
        sender = QLabSender()
        # OSC with integer argument
        packet = sender._build_osc("/dict/key", [42])
        assert b"/dict/key" in packet

    def test_cue_go(self):
        sender = QLabSender()
        # Should not raise — no actual network needed to build packet
        sender.cue_go(5)
        sender.cue_stop(3)
        sender.cue_pause(7)

    def test_panic(self):
        sender = QLabSender()
        sender.panic()  # Should not raise


class TestQLabWatcher:
    def test_fire_tracks_cue(self):
        sender = QLabSender()
        watcher = QLabWatcher(sender=sender)
        watcher.fire(1)
        assert watcher.is_cue_active(1)
        assert not watcher.is_cue_active(2)

    def test_complete_untracks(self):
        sender = QLabSender()
        watcher = QLabWatcher(sender=sender)
        watcher.fire(1)
        watcher.on_cue_complete(1)
        assert not watcher.is_cue_active(1)

    def test_no_refire_active_cue(self):
        sender = QLabSender()
        watcher = QLabWatcher(sender=sender)
        watcher.fire(1)
        # Refire should not raise, but does nothing
        watcher.fire(1)  # Should return without re-firing
        assert len(watcher._running_cues) == 1

    def test_stop_all_clears(self):
        sender = QLabSender()
        watcher = QLabWatcher(sender=sender)
        watcher.fire(1)
        watcher.fire(2)
        assert len(watcher._running_cues) == 2
        watcher.stop_all()
        assert len(watcher._running_cues) == 0

    def test_status(self):
        sender = QLabSender()
        watcher = QLabWatcher(sender=sender)
        watcher.fire(3)
        watcher.fire(7)
        status = watcher.status()
        assert status["count"] == 2
        assert 3 in status["active_cues"]
        assert 7 in status["active_cues"]
