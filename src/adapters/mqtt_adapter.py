"""MQTT adapter — bridge Good Theatre Engine to an external MQTT broker.

Subscribes to MQTT topics and converts received messages into UniversalMessage
objects on the internal MessageBus. Publishes GTE output_command messages to
the MQTT broker so external systems can consume them.

Broker is assumed to be running externally (e.g. Mosquitto, EMQX).
This adapter is the bridge — it does not run a broker.

Topics:
    Inbound  (subscribe):  gte/sensor/{source}   — sensor events from external systems
                            gte/event/{type}       — external events tagged for GTE
    Outbound (publish):     gte/output/{target}   — GTE output commands
                            gte/event/{type}       — GTE phase/transition events
                            gte/status            — heartbeat / status

Payload format (JSON):
    {"timestamp": 1234567890.0, "source": "...", "payload": {...}}
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None


# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

INBOUND_TOPICS = [
    "gte/sensor/#",      # sensor events from any source
    "gte/event/#",       # generic events
]

OUTBOUND_TOPICS = {
    "output_command": "gte/output/{target}",
    "phase_change":   "gte/event/phase",
    "pattern":         "gte/event/pattern",
    "heartbeat":       "gte/status",
}


# ------------------------------------------------------------------
# Message conversion
# ------------------------------------------------------------------

def mqtt_payload_to_message(
    topic: str,
    payload_bytes: bytes,
    source_name: str = "mqtt",
) -> dict[str, Any] | None:
    """Parse an inbound MQTT message into a dict for UniversalMessage.from_dict().

    Returns None if the payload is not valid JSON or is otherwise unparseable.
    """
    try:
        raw = json.loads(payload_bytes.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(raw, dict):
        return None

    # Normalise to UniversalMessage field names
    return {
        "id":        raw.get("id", ""),
        "timestamp": float(raw.get("timestamp", time.time())),
        "type":      str(raw.get("type", "sensor_event")),
        "source":    str(raw.get("source", source_name)),
        "payload":   dict(raw.get("payload", raw)),
        "metadata":  dict(raw.get("metadata", {})),
    }


def message_to_mqtt_payload(msg_dict: dict[str, Any]) -> bytes:
    """Serialise a GTE message dict to JSON bytes for MQTT publishing."""
    return json.dumps(msg_dict, separators=(",", ":")).encode("utf-8")


# ------------------------------------------------------------------
# MQTT Adapter
# ------------------------------------------------------------------

@dataclass
class MQTTAdapter:
    """Bridge between an external MQTT broker and the GTE MessageBus.

    The adapter runs two independent channels:
      subscriber  — connects as MQTT client, subscribes to inbound topics,
                    converts messages and passes them to on_message() callback
      publisher   — receives messages via publish() and sends them to the broker

    Both directions can be used independently.

    Usage:
        adapter = MQTTAdapter(broker_host="192.168.1.50", broker_port=1883)

        # Route inbound MQTT → MessageBus
        def on_inbound(msg):
            bus.publish(msg)
        adapter.on_message = on_inbound

        # Route MessageBus → outbound MQTT
        adapter.start()
        bus.subscribe(MessageType.OUTPUT_COMMAND, adapter.publish)

        # Or use publish() directly:
        adapter.publish_output("lights", {"action": "fade", "value": 0.8})
    """

    broker_host: str = "localhost"
    broker_port: int = 1883
    client_id: str = "gte-mqtt-adapter"
    keepalive: int = 60
    source_name: str = "mqtt"

    _client: Any = field(default=None, init=False)
    _running: bool = False
    _on_message: Callable[[dict], None] | None = field(default=None, init=False)
    _heartbeat_interval: float = 30.0
    _last_heartbeat: float = field(default_factory=time.time)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Connect to the MQTT broker and start the network loop."""
        if self._running:
            return
        if mqtt is None:
            raise ImportError("paho-mqtt is required: pip install paho-mqtt")

        client = mqtt.Client(client_id=self.client_id, clean_session=True)
        client.on_connect = self._on_connect
        client.on_message = self._on_message_cb
        client.on_disconnect = self._on_disconnect

        client.connect_async(self.broker_host, self.broker_port, keepalive=self.keepalive)
        client.loop_start()
        self._client = client
        self._running = True

    def stop(self) -> None:
        """Disconnect and stop the network loop."""
        self._running = False
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            for topic in INBOUND_TOPICS:
                client.subscribe(topic, qos=0)
        # else: could log warning — don't raise since broker might not be up yet in dev

    def _on_disconnect(self, client, userdata, rc):
        self._running = False

    def _on_message_cb(self, client, userdata, msg: mqtt.MQTTMessage):
        """Called for every inbound MQTT message."""
        msg_dict = mqtt_payload_to_message(msg.topic, msg.payload, self.source_name)
        if msg_dict is not None and self._on_message:
            self._on_message(msg_dict)

    # ------------------------------------------------------------------
    # Inbound API
    # ------------------------------------------------------------------

    @property
    def on_message(self) -> Callable[[dict], None] | None:
        """Callback for inbound messages from MQTT broker."""
        return self._on_message

    @on_message.setter
    def on_message(self, fn: Callable[[dict], None]) -> None:
        self._on_message = fn

    # ------------------------------------------------------------------
    # Publish API — outbound to MQTT broker
    # ------------------------------------------------------------------

    def publish_output(self, target: str, payload: dict[str, Any]) -> None:
        """Publish a GTE output command to the MQTT broker.

        Topic: gte/output/{target}
        """
        topic = OUTBOUND_TOPICS["output_command"].format(target=target)
        self._publish(topic, {
            "timestamp": time.time(),
            "type": "output_command",
            "source": "gte",
            "payload": {"target": target, **payload},
        })

    def publish_phase_change(self, from_region: str | None, to_region: str, trigger: str) -> None:
        """Publish a GTE phase/region transition to the MQTT broker.

        Topic: gte/event/phase
        """
        topic = OUTBOUND_TOPICS["phase_change"]
        self._publish(topic, {
            "timestamp": time.time(),
            "type": "phase_change",
            "source": "gte",
            "payload": {
                "from": from_region,
                "to": to_region,
                "trigger": trigger,
            },
        })

    def publish_pattern(self, pattern: dict[str, Any]) -> None:
        """Publish a learned pattern event to the MQTT broker.

        Topic: gte/event/pattern
        """
        topic = OUTBOUND_TOPICS["pattern"]
        self._publish(topic, {
            "timestamp": time.time(),
            "type": "pattern",
            "source": "gte",
            "payload": pattern,
        })

    def publish_heartbeat(self) -> None:
        """Publish a heartbeat status message to the MQTT broker.

        Topic: gte/status
        Sent automatically every _heartbeat_interval seconds when running.
        """
        topic = OUTBOUND_TOPICS["heartbeat"]
        self._publish(topic, {
            "timestamp": time.time(),
            "type": "heartbeat",
            "source": "gte",
            "payload": {
                "running": self._running,
                "connected": self._client.is_connected() if self._client else False,
            },
        })

    def _publish(self, topic: str, msg_dict: dict[str, Any]) -> None:
        """Internal publish — send a serialised dict to the MQTT broker."""
        if self._client and self._client.is_connected():
            self._client.publish(topic, message_to_mqtt_payload(msg_dict), qos=0, retain=False)

    # ------------------------------------------------------------------
    # Tick — call this from the engine run loop for heartbeat
    # ------------------------------------------------------------------

    def tick(self) -> None:
        """Send a heartbeat if the interval has elapsed. Call in run loop."""
        now = time.time()
        if now - self._last_heartbeat >= self._heartbeat_interval:
            self.publish_heartbeat()
            self._last_heartbeat = now

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        return {
            "type": "mqtt_adapter",
            "broker_host": self.broker_host,
            "broker_port": self.broker_port,
            "connected": self._client.is_connected() if self._client else False,
            "running": self._running,
            "subscribed_topics": INBOUND_TOPICS,
            "heartbeat_interval": self._heartbeat_interval,
        }
