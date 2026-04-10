"""Tests for Zigbee2MQTT adapter."""
from __future__ import annotations

import pytest
from src.adapters.inputs.zigbee import (
    ZigbeeAdapter,
    ZigbeeDevice,
    infer_capabilities,
    parse_z2m_mqtt_payload,
    parse_z2m_mqtt_topic,
)


class TestParseZ2MTopic:
    def test_standard_device_topic(self):
        name, attr = parse_z2m_mqtt_topic("zigbee2mqtt/Front%20PIR/state")
        assert name == "Front PIR"
        assert attr == "state"

    def test_set_topic(self):
        name, attr = parse_z2m_mqtt_topic("zigbee2mqtt/Stage%20Dimmer/set")
        assert name == "Stage Dimmer"
        assert attr == "set"

    def test_attribute_topic(self):
        name, attr = parse_z2m_mqtt_topic("zigbee2mqtt/Bathroom/illuminance")
        assert name == "Bathroom"
        assert attr == "illuminance"

    def test_unrelated_topic(self):
        result = parse_z2m_mqtt_topic("homeassistant/sensor/xyz")
        assert result == (None, None)


class TestParseZ2MPayload:
    def test_motion_payload(self):
        payload = parse_z2m_mqtt_payload(b'{"occupancy": true, "battery": 87}')
        assert payload["occupancy"] is True
        assert payload["battery"] == 87

    def test_brightness_payload(self):
        payload = parse_z2m_mqtt_payload(b'{"state": "ON", "brightness": 180}')
        assert payload["state"] == "ON"
        assert payload["brightness"] == 180

    def test_invalid_json(self):
        payload = parse_z2m_mqtt_payload(b"not json")
        assert payload["raw"] == "not json"


class TestInferCapabilities:
    def test_lighting_exposes(self):
        d = {
            "exposes": [
                {"type": "light", "features": [{"name": "state", "feature": "state"}]},
                {"type": "light", "name": "brightness", "feature": "brightness"},
            ]
        }
        caps = infer_capabilities({"definition": d})
        assert "state" in caps
        assert "brightness" in caps

    def test_sensor_exposes(self):
        d = {
            "exposes": [
                {"type": "numeric", "name": "temperature", "feature": "temperature"},
                {"type": "binary", "name": "occupancy", "feature": "occupancy"},
            ]
        }
        caps = infer_capabilities({"definition": d})
        assert "temperature" in caps
        assert "occupancy" in caps


class TestZigbeeDevice:
    def test_device_capabilities(self):
        d = ZigbeeDevice(
            ieee_address="0x1234",
            friendly_name="Test",
            definition={
                "exposes": [
                    {"type": "light", "name": "state", "feature": "state"},
                    {"name": "brightness", "feature": "brightness"},
                ]
            },
            raw={},
        )
        assert "state" in d.capabilities
        assert "brightness" in d.capabilities

    def test_device_online(self):
        d = ZigbeeDevice(
            ieee_address="0x1234",
            friendly_name="Test",
            definition={},
            raw={"availability": {"online": True}},
        )
        assert d.is_online is True

    def test_device_offline(self):
        d = ZigbeeDevice(
            ieee_address="0x1234",
            friendly_name="Test",
            definition={},
            raw={"availability": {"online": False}},
        )
        assert d.is_online is False

    def test_device_update_timestamp(self):
        d = ZigbeeDevice(
            ieee_address="0x1234",
            friendly_name="Test",
            definition={},
            raw={},
        )
        old = d._last_seen
        time.sleep(0.01)
        d.update({"brightness": 200})
        assert d._last_seen > old
        assert d.raw["brightness"] == 200


class TestZigbeeAdapter:
    def test_init(self):
        zb = ZigbeeAdapter(mqtt_host="mqtt://localhost", api_url="http://localhost:8080")
        assert zb.mqtt_host == "mqtt://localhost"
        assert zb.api_url == "http://localhost:8080"

    def test_status_initial(self):
        zb = ZigbeeAdapter()
        status = zb.status()
        assert status["type"] == "zigbee_adapter"
        assert status["mqtt_connected"] is False
        assert status["running"] is False

    def test_devices_empty_initially(self):
        zb = ZigbeeAdapter()
        assert zb.devices() == {}

    def test_callback_registration(self):
        zb = ZigbeeAdapter()
        called = []

        def handler(payload):
            called.append(payload)

        zb.on_device_event("Front PIR", handler)
        zb.on_device_event("*", handler)

        assert "Front PIR" in zb._callbacks
        assert "*" in zb._callbacks

    def test_set_builds_payload(self):
        zb = ZigbeeAdapter()
        zb._mqtt_client = MockMQTTClient()
        zb.set("Test Dimmer", on=True, brightness=200, transition=1.0)
        client = zb._mqtt_client
        assert len(client.published) == 1
        topic, payload_str = client.published[0]
        assert topic == "zigbee2mqtt/Test Dimmer/set"
        payload = json.loads(payload_str)
        assert payload["state"] == "ON"
        assert payload["brightness"] == 200
        assert payload["transition"] == 1.0

    def test_set_brightness_clamped(self):
        zb = ZigbeeAdapter()
        zb._mqtt_client = MockMQTTClient()
        zb.set("Dimmer", brightness=300)  # over max
        payload = json.loads(zb._mqtt_client.published[0][1])
        assert payload["brightness"] == 255

        zb.set("Dimmer", brightness=-10)  # under min
        payload = json.loads(zb._mqtt_client.published[1][1])
        assert payload["brightness"] == 0

    def test_set_cover_position(self):
        zb = ZigbeeAdapter()
        zb._mqtt_client = MockMQTTClient()
        zb.set("Curtain", position=50)
        payload = json.loads(zb._mqtt_client.published[0][1])
        assert payload["position"] == 50

    def test_set_extra_kwargs(self):
        zb = ZigbeeAdapter()
        zb._mqtt_client = MockMQTTClient()
        zb.set("Strip", xy=[0.64, 0.33], color_temp=300)
        payload = json.loads(zb._mqtt_client.published[0][1])
        assert payload["xy"] == [0.64, 0.33]
        assert payload["color_temp"] == 300


import json
import time


class MockMQTTClient:
    def __init__(self):
        self.published: list[tuple[str, str]] = []
        self._connected = True

    def is_connected(self):
        return self._connected

    def publish(self, topic: str, payload: str, qos=0, retain=False):
        self.published.append((topic, payload))
