from src.core.bus import MessageBus
from src.core.interface import InterfaceLayer
from src.core.knowledge import KnowledgeBase
from src.core.message import Priority, human_input, output_command


def test_interface_logs_and_routes(tmp_path):
    bus = MessageBus()
    kb = KnowledgeBase(str(tmp_path / "kb"))
    interface = InterfaceLayer(bus, kb, log_dir=str(tmp_path / "events"))
    seen = []
    bus.subscribe_all(lambda msg: seen.append(msg.source))
    interface.receive(human_input("cli", {"text": "go"}))
    assert seen == ["cli"]
    assert interface.event_log_path.exists()


def test_mandatory_gate_blocks_unapproved_critical(tmp_path):
    bus = MessageBus()
    kb = KnowledgeBase(str(tmp_path / "kb"))
    interface = InterfaceLayer(bus, kb, gate_mode="mandatory", log_dir=str(tmp_path / "events"))
    seen = []
    bus.subscribe_all(lambda msg: seen.append(msg.source))
    interface.receive(human_input("cli", {"text": "go"}, priority=Priority.CRITICAL))
    assert seen == []
