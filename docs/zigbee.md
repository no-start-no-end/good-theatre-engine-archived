# Zigbee Integration

[Zigbee2MQTT](https://www.zigbee2mqtt.org/) (Z2M) bridges the vast Zigbee device ecosystem to MQTT. The Good Theatre Engine speaks to Z2M via MQTT (device events and commands) and the Z2M REST API (device discovery).

Common theatrical Zigbee devices via Z2M:
- **Wireless dimmers / RGBWW controllers** — stage LED strips, practicals
- **PIR occupancy sensors** — audience presence detection
- **Wireless relay modules** — on/off control of non-DMX fixtures
- **Motorized curtain controllers** — fly systems, masking curtains
- **Philips Hue dimmer switches** — operator call buttons, stage manager remotes

## Architecture

```
Zigbee devices (PIR, dimmers, relays)
         ↕ (Zigbee radio)
Zigbee2MQTT (on a Raspberry Pi or server)
         ↕ (MQTT + REST)
Good Theatre Engine ← src/adapters/inputs/zigbee.py
```

## Setup

### 1 — Install Zigbee2MQTT

On a Raspberry Pi or server on your network:
```bash
# Follow https://zigbee2mqtt.org/guide/getting-started/
# Z2M exposes:
#   - MQTT broker on port 1883
#   - REST API on port 8080
```

### 2 — Install `paho-mqtt`

```bash
pip install paho-mqtt
```

### 3 — Pair your devices

In the Z2M web UI (port 8080), pair your Zigbee devices and rename them to friendly names (e.g. `Front PIR`, `Stage Dimmer`, `Main Curtain`).

## Basic Usage

```python
from src.adapters.inputs.zigbee import ZigbeeAdapter
from src.core.message import sensor_event

zb = ZigbeeAdapter(
    mqtt_host="mqtt://192.168.1.50",
    api_url="http://192.168.1.50:8080",
)

def on_motion(payload, attribute, device_name):
    if payload.get("occupancy"):
        print(f"Motion detected: {device_name}")

zb.on_device_event("Front PIR", on_motion)
zb.start()

# In your run loop:
# zb.set("Stage Dimmer", on=True, brightness=180, transition=1.0)
```

## Device Command Reference

```python
# Lighting
zb.set("Stage Dimmer", on=True, brightness=180, transition=1.0)  # fade in
zb.set("Stage Dimmer", off=True)                                  # fade out
zb.set("Side Strip", color_temp=300)                              # warm (153–500)
zb.set("RGB Bar", xy=[0.64, 0.33])                                # color

# Covers / curtains
zb.set("Main Curtain", position=50)  # 0=closed, 100=open
zb.set("Main Curtain", open=True)
zb.set("Main Curtain", close=True)
zb.set("Main Curtain", stop=True)

# Switches / relays
zb.set("Work Light", on=True)
zb.set("Work Light", off=True)
```

## Receiving Events

```python
# Per-device callback
zb.on_device_event("Front PIR", lambda p, a, n: print(f"{n}: {p}"))

# Global catch-all
zb.on_device_event("*", lambda p, a, n: bus.publish(sensor_event("zigbee", p)))
```

The callback receives: `(payload: dict, attribute: str, device_name: str)`

Common `payload` keys:
| Device type | Keys |
|------------|------|
| PIR sensor | `occupancy`, `battery`, `temperature` |
| Dimmer | `state` (ON/OFF), `brightness` (0-254) |
| RGBWW | `state`, `brightness`, `color_temp`, `xy` |
| Cover | `position` (0-100), `state` (open/closed/stop) |
| Switch | `action` (click/hold/release), `battery` |

## Integration with the Message Bus

```python
from src.adapters.inputs.zigbee import ZigbeeAdapter
from src.core.bus import MessageBus
from src.core.message import sensor_event

bus = MessageBus()
zb = ZigbeeAdapter(mqtt_host="mqtt://192.168.1.50", api_url="http://192.168.1.50:8080")

def forward_to_bus(payload, attribute, device_name):
    msg = sensor_event(
        source=f"zigbee.{device_name}",
        payload=payload,
        tags=["zigbee", f"zigbee_{device_name}"],
    )
    bus.publish(msg)

zb.on_device_event("*", forward_to_bus)
zb.start()

# Now Zigbee events flow through the bus like any other sensor
```

## Health Check

```python
from src.adapters.inputs.zigbee import ZigbeeAdapter

zb = ZigbeeAdapter(mqtt_host="mqtt://192.168.1.50", api_url="http://192.168.1.50:8080")
zb.start()

import time; time.sleep(2)
print(zb.status())
# {'type': 'zigbee_adapter', 'mqtt_connected': True, 'devices_known': 12, ...}
```

## Transition Times

Always use `transition=N` (seconds) for theatrical fades — sudden state changes are jarring:

```python
zb.set("Stage Dimmer", on=True, brightness=0, transition=0)    # instant black
zb.set("Stage Dimmer", on=True, brightness=255, transition=3.0) # 3-second fade up
```

## Troubleshooting

| Problem | Check |
|---------|-------|
| `ModuleNotFoundError: paho-mqtt` | `pip install paho-mqtt` |
| No devices discovered | Z2M REST API not reachable — check `api_url` |
| Commands not arriving at device | Z2M MQTT not connected — check `mqtt_host` |
| Device always shows offline | Z2M device is unreachable — check Zigbee signal strength |
