from src.ai.decision import DecisionEngine
from src.core.bus import MessageBus
from src.core.interface import InterfaceLayer
from src.core.knowledge import KnowledgeBase
from src.performance import PerformanceConfig, PerformanceRunner, Phase


def make_runner(tmp_path):
    bus = MessageBus()
    kb = KnowledgeBase(str(tmp_path / "kb"))
    interface = InterfaceLayer(bus, kb, log_dir=str(tmp_path / "events"))
    runner = PerformanceRunner(
        PerformanceConfig(name="Test Show", allowed_outputs=["lights", "audio", "display"], transition_min_duration=0.0),
        kb,
        interface,
        DecisionEngine(kb),
        phase_configs={
            Phase.INTRO: PerformanceConfig("Test Show", Phase.INTRO, 0.3, ["lights", "audio", "display"], 0.0),
            Phase.ACT_1: PerformanceConfig("Test Show", Phase.ACT_1, 0.7, ["lights", "audio"], 0.0),
            Phase.OUTRO: PerformanceConfig("Test Show", Phase.OUTRO, 0.1, ["lights"], 0.0),
        },
    )
    return runner, kb


def test_performance_runner_start_transition_and_end(tmp_path):
    runner, kb = make_runner(tmp_path)
    runner.start()
    assert runner.is_running is True
    assert kb.load_state().phase == "detecting"

    runner.transition_to(Phase.ACT_1)
    state = kb.load_state()
    assert state.phase == "stabilizing"
    assert state.constraints["allowed_outputs"] == ["lights", "audio"]
    assert runner.phase_elapsed >= 0.0

    runner.end()
    assert runner.is_running is False
    assert kb.load_state().phase == "dispersing"


def test_performance_runner_pause_resume_and_emergency(tmp_path):
    runner, kb = make_runner(tmp_path)
    runner.start()
    runner.pause()
    assert runner.is_paused is True
    runner.resume()
    assert runner.is_paused is False

    runner.emergency_stop()
    state = kb.load_state()
    assert runner.is_running is False
    assert state.phase == "emergency_stop"
    assert state.energy_level == 0.0
