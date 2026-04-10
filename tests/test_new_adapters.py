from src.adapters.inputs.keyboard import KeyboardAdapter
from src.adapters.outputs.osc import OSCAdapter
from src.core.message import Priority, output_command


def test_keyboard_adapter_translates_keys():
    adapter = KeyboardAdapter()
    emergency = adapter._translate_key("\x1b")
    assert emergency is not None
    assert emergency.payload["action"] == "emergency_stop"
    assert emergency.metadata.priority == Priority.CRITICAL

    phase = adapter._translate_key("2")
    assert phase is not None
    assert phase.payload == {"action": "transition", "phase": "stabilizing", "approved": True}


def test_osc_adapter_builds_messages_and_tracks_status():
    adapter = OSCAdapter()
    packet = adapter._build_message("/dmx/1", [0.5, 3])
    assert packet.startswith(b"/dmx/1")

    adapter.send(output_command("lights", {"action": "fade", "channel": 4, "value": 0.7, "duration": 1.5}))
    status = adapter.status()
    assert status["sent_count"] == 1
    assert status["last_message"]["address"] == "/dmx/4/fade"
