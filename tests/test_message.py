from src.core.message import MessageType, Priority, UniversalMessage, human_input, output_command, sensor_event


def test_message_roundtrip():
    message = sensor_event("sensor", {"motion": True})
    restored = UniversalMessage.from_dict(message.to_dict())
    assert restored.type == MessageType.SENSOR_EVENT
    assert restored.payload["motion"] is True


def test_human_input_priority():
    message = human_input("cli", {"text": "go"}, priority=Priority.CRITICAL)
    assert message.metadata.priority == Priority.CRITICAL


def test_output_command_target():
    message = output_command("lights", {"action": "fade"})
    assert message.payload["target"] == "lights"
