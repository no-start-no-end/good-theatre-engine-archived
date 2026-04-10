from src.core.bus import MessageBus
from src.core.message import sensor_event


def test_publish_to_subscriber():
    bus = MessageBus()
    seen = []
    bus.subscribe_all(lambda msg: seen.append(msg.source))
    bus.publish(sensor_event("sensor", {"ok": True}))
    assert seen == ["sensor"]
