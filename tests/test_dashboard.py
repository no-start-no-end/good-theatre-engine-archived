from src.adapters.outputs.mock import MockAudioAdapter, MockDisplayAdapter, MockLightAdapter
from src.ai.decision import DecisionEngine
from src.core.bus import MessageBus
from src.core.interface import InterfaceLayer
from src.core.knowledge import KnowledgeBase
from src.core.message import sensor_event
from src.operators.dashboard import Dashboard
from src.performance import PerformanceConfig, PerformanceRunner


def test_dashboard_snapshot_contains_control_room_state(tmp_path):
    bus = MessageBus()
    kb = KnowledgeBase(str(tmp_path / "kb"))
    interface = InterfaceLayer(bus, kb, log_dir=str(tmp_path / "events"))
    runner = PerformanceRunner(
        PerformanceConfig(name="Test Show", allowed_outputs=["lights", "audio", "display"], transition_min_duration=0.0),
        kb,
        interface,
        DecisionEngine(kb),
    )
    dashboard = Dashboard(
        interface,
        kb,
        DecisionEngine(kb),
        outputs={"lights": MockLightAdapter(), "audio": MockAudioAdapter(), "display": MockDisplayAdapter()},
        performance_runner=runner,
    )

    runner.start()
    interface.receive(sensor_event("motion", {"movement_level": 0.9}))
    snap = dashboard.snapshot()

    assert snap["state"]["phase"] == "detecting"
    assert "phase_color" in snap["performance"]
    assert len(snap["timeline"]) >= 1
    assert set(snap["outputs"].keys()) == {"lights", "audio", "display"}
