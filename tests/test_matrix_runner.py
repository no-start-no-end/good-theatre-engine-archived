"""Tests for MatrixRunner."""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock
import pytest
from src.matrix_runner import MatrixRunner, Mode, PhaseTransition
from src.performance_matrix import PhaseSpace
from src.performance import Phase, PerformanceConfig


# Minimal fakes to avoid importing the full engine
class FakeKnowledge:
    def load_state(self): return MagicMock(phase="detecting", energy_level=0.5)
    def save_state(self, s): pass


class FakeInterface:
    def receive(self, msg): pass


class FakeDecision:
    pass


def make_space():
    space = PhaseSpace()
    space.add_dimension("energy", current=0.2, min=0.0, max=1.0)
    space.add_region("detecting", {"energy": (0.0, 0.3)})
    space.add_region("stabilizing", {"energy": (0.3, 0.7)})
    space.add_region("dispersing", {"energy": (0.0, 0.15)})
    return space


def make_phase_configs():
    return {
        Phase.INTRO: PerformanceConfig(name="Detecting", phase=Phase.INTRO),
        Phase.ACT_1: PerformanceConfig(name="Stabilizing", phase=Phase.ACT_1),
        Phase.OUTRO: PerformanceConfig(name="Dispersing", phase=Phase.OUTRO),
    }


def make_runner(space=None, mode=Mode.MATRIX_FIRST, phase_configs=None):
    if space is None:
        space = make_space()
    return MatrixRunner(
        space=space,
        knowledge=FakeKnowledge(),
        interface=FakeInterface(),
        decision_engine=FakeDecision(),
        dimension_driver=None,
        phase_configs=phase_configs or make_phase_configs(),
        mode=mode,
    )


class TestMatrixRunner:
    def test_start_stop(self):
        runner = make_runner()
        assert runner.is_running is False
        runner.start()
        assert runner.is_running is True
        runner.stop()
        assert runner.is_running is False

    def test_jump_transitions_space_and_fires_callback(self):
        runner = make_runner()
        entered = []

        runner.on_phase_enter("stabilizing", lambda s: entered.append("stabilizing"))
        runner.jump("stabilizing")

        assert runner.current_region == "stabilizing"
        assert entered == ["stabilizing"]

    def test_jump_unknown_raises(self):
        runner = make_runner()
        with pytest.raises(KeyError):
            runner.jump("nonexistent")

    def test_tick_push_detects_transition(self):
        runner = make_runner()
        entered = []

        runner.on_phase_enter("stabilizing", lambda s: entered.append("stabilizing"))
        runner.jump("detecting")
        runner.space.set("energy", 0.5)  # push into stabilizing range
        result = runner.tick(delta_seconds=0.0)

        assert runner.current_region == "stabilizing"
        assert entered == ["stabilizing"]
        assert result.name == "stabilizing"

    def test_jump_does_not_duplicate_callback_on_enter(self):
        """Jump fires enter once even if already in the target space."""
        runner = make_runner()
        entered = []
        runner.on_phase_enter("stabilizing", lambda s: entered.append("stabilizing"))
        runner.jump("stabilizing")
        runner.jump("stabilizing")  # again — no-op
        assert entered == ["stabilizing"]

    def test_status_includes_region_and_phase(self):
        runner = make_runner()
        runner.jump("detecting")
        status = runner.status()
        assert status["current_region"] == "detecting"
        assert status["current_phase"] == Phase.INTRO.value

    def test_transition_log_records_jump(self):
        runner = make_runner()
        runner.jump("detecting")
        runner.jump("stabilizing")
        status = runner.status()
        log = status["transitions"]
        assert len(log) == 2
        assert log[0]["from"] is None
        assert log[0]["to"] == "detecting"
        assert log[0]["trigger"] == "jump"
        assert log[1]["from"] == "detecting"
        assert log[1]["to"] == "stabilizing"
        assert log[1]["trigger"] == "jump"

    def test_operator_override(self):
        runner = make_runner()
        entered = []
        runner.on_phase_enter("dispersing", lambda s: entered.append("dispersing"))
        runner.operator_override("dispersing")
        assert entered == ["dispersing"]
        # Check transition log has "operator" trigger
        assert runner.status()["transitions"][-1]["trigger"] == "operator"

    def test_sequence_first_mode_syncs_space_to_perf(self):
        """In sequence_first mode, space follows PerformanceRunner's phase."""
        runner = make_runner(mode=Mode.SEQUENCE_FIRST)
        runner.jump("detecting")
        # Manually transition the perf runner — space should follow
        runner.performance_runner.transition_to(Phase.ACT_1)
        runner.tick(delta_seconds=0.0)
        # Space should have jumped to stabilizing to match the phase
        assert runner.current_region == "stabilizing"

    def test_on_phase_enter_same_callback_multiple_times(self):
        """Registering the same callback multiple times adds it multiple times."""
        runner = make_runner()
        count = [0]

        def cb(s):
            count[0] += 1

        runner.on_phase_enter("stabilizing", cb)
        runner.on_phase_enter("stabilizing", cb)
        runner.jump("stabilizing")
        assert count[0] == 2

    def test_status_includes_transition_log(self):
        runner = make_runner()
        runner.jump("detecting")
        runner.jump("stabilizing")
        status = runner.status()
        assert len(status["transitions"]) == 2
        assert status["transitions"][0]["to"] == "detecting"
        assert status["transitions"][1]["to"] == "stabilizing"

    def test_current_phase_matches_region(self):
        runner = make_runner()
        runner.jump("detecting")
        assert runner.current_phase == Phase.INTRO
        runner.jump("stabilizing")
        assert runner.current_phase == Phase.ACT_1
