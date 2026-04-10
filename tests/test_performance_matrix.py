"""Tests for the phase space matrix."""
from __future__ import annotations

import time
import pytest
from src.performance_matrix import Dimension, PhaseRegion, PhaseSpace


class TestDimension:
    def test_creation(self):
        d = Dimension(name="energy", current=0.5, min=0.0, max=1.0, velocity=0.0)
        assert d.current == 0.5
        assert d.min == 0.0
        assert d.max == 1.0
        assert d.velocity == 0.0

    def test_set_clamps_to_range(self):
        d = Dimension(name="energy", current=0.5, min=0.0, max=1.0)
        d.set(1.5)
        assert d.current == 1.0
        d.set(-0.5)
        assert d.current == 0.0

    def test_update_with_velocity(self):
        d = Dimension(name="energy", current=0.0, min=0.0, max=1.0, velocity=0.5)
        d.update(1.0)  # 1 second at 0.5/s
        assert d.current == pytest.approx(0.5)
        d.update(2.0)  # 2 more seconds
        assert d.current == pytest.approx(1.0)  # clamped at max


class TestPhaseSpace:
    def test_add_dimension(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.2, min=0.0, max=1.0)
        assert "energy" in space.dimensions
        assert space.get("energy") == 0.2

    def test_set_dimension(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.2, min=0.0, max=1.0)
        space.set("energy", 0.8)
        assert space.get("energy") == 0.8

    def test_set_unknown_dimension_raises(self):
        space = PhaseSpace()
        with pytest.raises(KeyError):
            space.set("nonexistent", 0.5)

    def test_snapshot(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.2, min=0.0, max=1.0)
        space.add_dimension("tempo", current=80, min=20, max=140)
        snap = space.snapshot()
        assert snap["energy"] == 0.2
        assert snap["tempo"] == 80

    def test_add_region(self):
        space = PhaseSpace()
        space.add_region("detecting", {
            "energy": (0.0, 0.3),
            "tempo": (40, 70),
        })
        assert "detecting" in space.regions

    def test_no_initial_region(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.2, min=0.0, max=1.0)
        space.add_region("detecting", {"energy": (0.0, 0.3)})
        assert space.current_region() is None

    def test_jump_to_region(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.2, min=0.0, max=1.0)
        space.add_region("detecting", {"energy": (0.0, 0.3)})
        space.add_region("stabilizing", {"energy": (0.3, 0.7)})

        entered = []
        space.on_enter("stabilizing", lambda s: entered.append("stabilizing"))

        space.jump("stabilizing")
        assert space.current_region() == "stabilizing"
        assert entered == ["stabilizing"]

    def test_jump_unknown_region_raises(self):
        space = PhaseSpace()
        with pytest.raises(KeyError):
            space.jump("nonexistent")

    def test_push_detects_region_entry(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.1, min=0.0, max=1.0)
        space.add_region("detecting", {"energy": (0.0, 0.3)})
        space.add_region("stabilizing", {"energy": (0.3, 0.7)})

        entered = []
        space.on_enter("stabilizing", lambda s: entered.append("stabilizing"))

        # Jump to intro first
        space.jump("detecting")
        assert space.current_region() == "detecting"

        # Push energy into act_1 range
        space.set("energy", 0.5)
        result = space.tick(delta_seconds=0.0)

        assert space.current_region() == "stabilizing"
        assert entered == ["stabilizing"]
        assert result.name == "stabilizing"

    def test_push_no_transition_when_already_in_region(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.2, min=0.0, max=1.0)
        space.add_region("detecting", {"energy": (0.0, 0.3)})

        space.jump("detecting")
        space.set("energy", 0.25)
        result = space.tick(delta_seconds=0.0)

        assert space.current_region() == "detecting"
        assert result is None

    def test_velocity_automatically_pushes(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.1, min=0.0, max=1.0)
        space.add_region("detecting", {"energy": (0.0, 0.3)})
        space.add_region("stabilizing", {"energy": (0.3, 0.7)})

        entered = []
        space.on_enter("stabilizing", lambda s: entered.append("stabilizing"))

        space.jump("detecting")
        space.set_velocity("energy", 0.5)  # 0.5 per second

        # Tick 1s → energy goes from 0.1 to 0.6 → crosses into act_1
        result = space.tick(delta_seconds=1.0)

        assert space.current_region() == "stabilizing"
        assert entered == ["stabilizing"]

    def test_exit_callback_fired(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.2, min=0.0, max=1.0)
        space.add_region("detecting", {"energy": (0.0, 0.3)})
        space.add_region("stabilizing", {"energy": (0.3, 0.7)})

        exited = []
        entered = []

        space.on_exit("detecting", lambda s: exited.append("detecting"))
        space.on_enter("stabilizing", lambda s: entered.append("stabilizing"))

        space.jump("detecting")
        space.set("energy", 0.5)
        space.tick(delta_seconds=0.0)

        assert exited == ["detecting"]
        assert entered == ["stabilizing"]

    def test_status(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.2, min=0.0, max=1.0)
        space.add_region("detecting", {"energy": (0.0, 0.3)})

        status = space.status()
        assert status["current_region"] is None
        assert status["dimensions"] == {"energy": 0.2}
        assert status["regions"] == ["detecting"]

    def test_multi_dimension_push(self):
        """Push requires ALL dimension boundaries to be satisfied."""
        space = PhaseSpace()
        space.add_dimension("energy", current=0.1, min=0.0, max=1.0)
        space.add_dimension("tempo", current=50, min=20, max=140)
        space.add_region("detecting", {
            "energy": (0.0, 0.3),
            "tempo": (40, 70),
        })
        space.add_region("stabilizing", {
            "energy": (0.3, 0.7),
            "tempo": (70, 100),
        })

        entered = []
        space.on_enter("stabilizing", lambda s: entered.append("stabilizing"))

        space.jump("detecting")

        # Only energy in act_1 range, tempo still in intro → no push
        space.set("energy", 0.5)
        space.tick(delta_seconds=0.0)
        assert space.current_region() == "detecting"

        # Both dimensions in act_1 range → push triggers
        space.set("tempo", 85)
        space.tick(delta_seconds=0.0)
        assert space.current_region() == "stabilizing"
        assert entered == ["stabilizing"]

    def test_jump_while_already_in_region_no_op(self):
        """Jumping to the current region does nothing."""
        space = PhaseSpace()
        space.add_dimension("energy", current=0.2, min=0.0, max=1.0)
        space.add_region("detecting", {"energy": (0.0, 0.3)})

        entered = []
        space.on_enter("detecting", lambda s: entered.append("detecting"))

        space.jump("detecting")
        space.jump("detecting")  # again

        assert entered == ["detecting"]  # only once

    def test_set_velocity(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.0, min=0.0, max=1.0)
        space.set_velocity("energy", 0.2)
        assert space.dimensions["energy"].velocity == 0.2

    def test_set_velocity_unknown_raises(self):
        space = PhaseSpace()
        with pytest.raises(KeyError):
            space.set_velocity("nonexistent", 0.5)
