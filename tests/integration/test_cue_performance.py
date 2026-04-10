"""Integration test: wire together cues + performance + decision engine."""
from __future__ import annotations

import time
import pytest
from src.cues import CueList
from src.cues.runner import CueRunner
from src.core.bus import MessageBus
from src.core.interface import InterfaceLayer
from src.core.knowledge import KnowledgeBase
from src.core.message import MessageType, UniversalMessage, sensor_event
from src.ai.decision import DecisionEngine


class TestCueIntegration:
    """Wire cues → interface → decision → output and verify the full loop."""

    def test_cue_list_fires(self, tmp_path):
        """CueRunner fires cues in offset order, converting targets to output commands."""
        cues = CueList("Test Integration")
        cues.add_go(1, "First cue", {"lights": {"channel": 1, "value": 0.8}})
        cues.add_go(2, "Second cue", {"audio": {"volume": 0.6}})

        bus = MessageBus()
        knowledge = KnowledgeBase(str(tmp_path))
        interface = InterfaceLayer(bus, knowledge, gate_mode="bypass", log_dir=str(tmp_path))

        output_messages = []
        def capture(msg: UniversalMessage):
            output_messages.append(msg)

        bus.subscribe(MessageType.OUTPUT_COMMAND, capture)

        runner = CueRunner(cue_list=cues, interface=interface)
        runner.start()
        time.sleep(3)
        runner.stop()

        fired = [m for m in output_messages if m.source.startswith("cue.")]
        assert len(fired) >= 1
        assert any("lights" in m.payload.get("target", "") for m in fired)

    def test_decision_engine_zones(self):
        """Decision engine applies zone-aware lighting response."""
        bus = MessageBus()
        knowledge = KnowledgeBase("./logs")
        decision = DecisionEngine(knowledge)
        interface = InterfaceLayer(bus, knowledge, gate_mode="bypass", log_dir="./logs")

        msg = sensor_event(
            "motion.stage_left",
            {"zone": "stage_left", "motion": True, "movement_level": 0.8},
            tags=["motion", "stage_left"],
        )
        context = knowledge.get_context()
        results = decision.process(msg, context)
        assert len(results) >= 1
        assert any("lights" in r.payload.get("target", "") for r in results)

    def test_performance_phases(self, tmp_path):
        """PerformanceRunner transitions between phases correctly."""
        from src.performance import PerformanceConfig, PerformanceRunner, Phase

        bus = MessageBus()
        knowledge = KnowledgeBase(str(tmp_path))
        interface = InterfaceLayer(bus, knowledge, gate_mode="bypass", log_dir=str(tmp_path))
        decision = DecisionEngine(knowledge)

        config = PerformanceConfig("Test", Phase.INTRO, 0.3, ["lights", "audio"], 0.5, True)
        phase_configs = {
            Phase.INTRO: config,
            Phase.ACT_1: PerformanceConfig("Test", Phase.ACT_1, 0.6, ["lights", "audio"], 0.5, True),
            Phase.OUTRO: PerformanceConfig("Test", Phase.OUTRO, 0.1, ["lights"], 0.5, True),
        }
        runner = PerformanceRunner(config, knowledge, interface, decision, phase_configs=phase_configs)

        assert not runner.is_running
        runner.start()
        assert runner.is_running
        assert runner.config.phase == Phase.INTRO

        runner.transition_to(Phase.ACT_1)
        assert runner.config.phase == Phase.ACT_1

        runner.end()
        assert not runner.is_running
