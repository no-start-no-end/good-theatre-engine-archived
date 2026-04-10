"""Zigbee2MQTT adapter — bridge the Good Theatre Engine to Zigbee devices.

Zigbee2MQTT (Z2M) exposes Zigbee devices over:
- MQTT: subscribe to device state changes
- REST API: query device list and state

This adapter:
- Subscribes to MQTT for real-time device events
- Polls the Z2M REST API for state snapshots on startup
- Sends commands via MQTT to set device state

Common theatrical Zigbee devices via Z2M:
- Wireless dimmers (e.g., Philips Hue dimmer switch)
- PIR occupancy sensors
- Wireless relay modules (on/off control)
- RGBWW controllers for LED strips
- Motorized curtain controllers

Configuration:
    MQTT_HOST=mqtt://192.168.1.50:1883
    Z2M_API=http://192.168.1.50:8080
"""
from __future__ import annotations

import json
import socket
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None


# ------------------------------------------------------------------
# Device type registry
# ------------------------------------------------------------------

ZIGBEE_CAPABILITIES = {
    # Common Zigbee device classes and their output capabilities
    "lighting": ["on", "off", "brightness", "color_temp", "xy", "hs"],
    "switch":   ["on", "off", "click", "hold", "release"],
    "sensor":   ["temperature", "humidity", "motion", "illuminance", "battery"],
    "cover":    ["position", "tilt", "open", "close", "stop"],
    "lock":     ["locked", "unlocked"],
    "thermostat": ["temperature", "occupied_heating_setpoint", "mode"],
}


def infer_capabilities(device: dict[str, Any]) -> list[str]:
    """Return a list of likely capabilities based on device definition.

    Supports two Z2M data layouts:
    - Device dict: {"definition": {"exposes": [...]}}   (from Z2M /api/devices)
    - Direct definition: {"exposes": [...]}                 (used in tests)
    """
    definition = device.get("definition", device)  # device dict or direct def
    exposed = definition.get("exposes", [])
    caps = []
    for e in exposed:
        if isinstance(e, dict):
            features = e.get("features", [])
            if features:
                for f in features:
                    feat = f.get("feature", f.get("name", ""))
                    if feat:
                        caps.append(feat)
            else:
                feat = e.get("feature", e.get("name", ""))
                if feat:
                    caps.append(feat)
        elif isinstance(e, str):
            caps.append(e)
    return caps


# ------------------------------------------------------------------
# MQTT message parsing
# ------------------------------------------------------------------

def parse_z2m_mqtt_topic(topic: str) -> tuple[Optional[str], Optional[str]]:
    """Parse 'zigbee2mqtt/<friendly_name>/<attribute>' → (device_name, attribute).

    Returns (None, None) if the topic doesn't match the expected pattern.
    """
    prefix = "zigbee2mqtt/"
    if not topic.startswith(prefix):
        return None, None
    rest = topic[len(prefix):]
    parts = rest.rsplit("/", 1)
    if len(parts) == 2:
        return urllib.parse.unquote(parts[0]), parts[1]
    return rest, None


def parse_z2m_mqtt_payload(payload: bytes) -> dict[str, Any]:
    """Parse a Z2M MQTT message payload.

    Z2M payloads are JSON. Occupancy, brightness, switch events — all here.
    """
    try:
        return json.loads(payload.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"raw": payload.decode("utf-8", errors="replace")}


# ------------------------------------------------------------------
# Main adapter
# ------------------------------------------------------------------

@dataclass
class ZigbeeDevice:
    """A discovered Zigbee device via Z2M."""

    ieee_address: str
    friendly_name: str
    definition: dict[str, Any]
    raw: dict[str, Any]
    _last_seen: float = field(default_factory=time.time)

    @property
    def capabilities(self) -> list[str]:
        return infer_capabilities(self.definition)

    @property
    def is_online(self) -> bool:
        return self.raw.get("availability", {}).get("online", True)

    def update(self, state: dict[str, Any]):
        self.raw.update(state)
        self._last_seen = time.time()


@dataclass
class ZigbeeAdapter:
    """Bridge to Zigbee2MQTT via MQTT + REST API.

    Subscribe to device state changes and send commands to Zigbee devices
    all through the standard Z2M MQTT interface.

    Usage:
        zb = ZigbeeAdapter(
            mqtt_host="mqtt://192.168.1.50",
            api_url="http://192.168.1.50:8080",
        )
        zb.on_device_event("Front PIR", lambda msg: bus.publish(msg))
        zb.start()

        # Fire a Zigbee device
        zb.set("Stage Dimmer", on=True, brightness=255)
    """

    mqtt_host: str = "mqtt://localhost"
    api_url: str = "http://localhost:8080"
    source_name: str = "zigbee"
    _devices: dict[str, ZigbeeDevice] = field(default_factory=dict)
    _callbacks: dict[str, Callable[[Any], None]] = field(default_factory=dict)
    _mqtt_client: Any = field(default=None, init=False)
    _running: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Start the MQTT subscriber and populate device list from API."""
        if self._running:
            return
        self._running = True

        if mqtt is None:
            raise ImportError("paho-mqtt is required: pip install paho-mqtt")

        # Discover devices via REST API
        self._discover_devices()

        # Connect MQTT
        host = self.mqtt_host.replace("mqtt://", "").split(":")
        mqtt_host = host[0]
        mqtt_port = int(host[1]) if len(host) > 1 else 1883

        client = mqtt.Client()
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.connect_async(mqtt_host, mqtt_port, keepalive=10)
        client.loop_start()
        self._mqtt_client = client

    def stop(self):
        """Disconnect and stop."""
        self._running = False
        if self._mqtt_client:
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()
            self._mqtt_client = None

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            client.subscribe("zigbee2mqtt/#", qos=0)
        else:
            # Could log here — don't raise since we might be in mock mode
            pass

    def _on_message(self, client, userdata, msg: mqtt.MQTTMessage):
        device_name, attribute = parse_z2m_mqtt_topic(msg.topic)
        if device_name is None:
            return

        payload = parse_z2m_mqtt_payload(msg.payload)

        # Update device state cache
        if device_name in self._devices:
            self._devices[device_name].update(payload)
        elif device_name != "":
            self._devices[device_name] = ZigbeeDevice(
                ieee_address=payload.get("ieee_address", ""),
                friendly_name=device_name,
                definition={},
                raw=payload,
            )

        # Invoke callbacks
        callback = self._callbacks.get(device_name) or self._callbacks.get("*")
        if callback:
            callback(payload, attribute, device_name)

    # ------------------------------------------------------------------
    # Device discovery
    # ------------------------------------------------------------------

    def _discover_devices(self):
        """Fetch device list from Z2M REST API."""
        try:
            import urllib.request
            url = f"{self.api_url.rstrip('/')}/api/devices"
            with urllib.request.urlopen(url, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for d in data:
                ieee = d.get("ieee_address", "")
                name = d.get("friendly_name", ieee)
                self._devices[name] = ZigbeeDevice(
                    ieee_address=ieee,
                    friendly_name=name,
                    definition=d.get("definition", {}),
                    raw=d,
                )
        except Exception:
            # Z2M not running or not reachable — that's fine in mock/dev mode
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_device_event(
        self,
        device_name: str,
        callback: Callable[[dict[str, Any]], None],
    ):
        """Register a callback for a specific device or all devices (name='*')."""
        self._callbacks[device_name] = callback

    def devices(self) -> dict[str, ZigbeeDevice]:
        """Return the current device registry."""
        return dict(self._devices)

    def device(self, name: str) -> Optional[ZigbeeDevice]:
        """Return a specific device by name."""
        return self._devices.get(name)

    def set(
        self,
        device_name: str,
        *,
        on: Optional[bool] = None,
        off: Optional[bool] = None,
        brightness: Optional[int] = None,
        color_temp: Optional[int] = None,
        xy: Optional[list[float]] = None,
        hs: Optional[dict[str, float]] = None,
        position: Optional[int] = None,  # 0-100 for covers
        transition: float = 0.5,
        **kwargs: Any,
    ):
        """Set a Zigbee device state via MQTT.

        Examples:
            zb.set("Stage Dimmer", on=True, brightness=180, transition=1.0)
            zb.set("Side Strip", color_temp=300)  # warm white
            zb.set("Main Curtain", position=50)    # half open
            zb.set("Work Light", on=True)         # simple on
        """
        payload: dict[str, Any] = {"transition": transition}
        if on is not None:
            payload["state"] = "ON" if on else "OFF"
        if off is not None:
            payload["state"] = "OFF"
        if brightness is not None:
            payload["brightness"] = max(0, min(255, int(brightness)))
        if color_temp is not None:
            payload["color_temp"] = max(153, min(500, int(color_temp)))  # Z2M range
        if xy is not None:
            payload["xy"] = xy
        if hs is not None:
            payload["hs"] = hs
        if position is not None:
            payload["position"] = max(0, min(100, int(position)))
        payload.update(kwargs)

        topic = f"zigbee2mqtt/{device_name}/set"
        self._mqtt_publish(topic, payload)

    def _mqtt_publish(self, topic: str, payload: dict[str, Any]):
        if self._mqtt_client:
            self._mqtt_client.publish(
                topic,
                json.dumps(payload),
                qos=0,
                retain=False,
            )

    def is_online(self) -> bool:
        """Return True if MQTT broker is connected."""
        return (
            self._mqtt_client is not None
            and self._mqtt_client.is_connected()
        )

    def status(self) -> dict[str, Any]:
        """Return adapter status with device summary."""
        return {
            "type": "zigbee_adapter",
            "mqtt_host": self.mqtt_host,
            "api_url": self.api_url,
            "mqtt_connected": self.is_online(),
            "devices_known": len(self._devices),
            "devices_online": sum(1 for d in self._devices.values() if d.is_online),
            "running": self._running,
        }
