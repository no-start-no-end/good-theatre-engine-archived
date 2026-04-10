# Writing new adapters

Every input and output in the system is an **adapter** — a Python class that translates between hardware and `UniversalMessage` objects. The rest of the engine never touches hardware directly.

## Input adapters

```python
from src.adapters.inputs.base import BaseInputAdapter

class MySensor(BaseInputAdapter):
    def start(self):
        # Initialise the hardware connection
        pass

    def stop(self):
        # Clean up (close sockets, threads, etc.)
        pass

    def read(self) -> UniversalMessage | None:
        # Poll hardware; return None if nothing new, or a UniversalMessage
        return None
```

`read()` should be non-blocking and cheap. Return `None` when nothing is ready — the engine polls in a tight loop.

## Output adapters

```python
from src.adapters.outputs.base import BaseOutputAdapter
from src.core.message import UniversalMessage

class MyLightDimmer(BaseOutputAdapter):
    def send(self, message: UniversalMessage):
        # Interpret message.payload as commands for your hardware
        action = message.payload.get("action")
        channel = message.payload.get("channel", 1)
        value = message.payload.get("value", 0.0)
        # ...
```

## Payload conventions for common actions

### Lights
```python
{"target": "lights", "action": "fade", "channel": 3, "value": 0.85, "duration": 2.0}
{"target": "lights", "action": "blackout"}
{"target": "lights", "action": "full"}
```

### Audio
```python
{"target": "audio", "action": "set_volume", "channel": 1, "volume": 0.6}
{"target": "audio", "action": "play_note", "channel": 1, "note": 60, "velocity": 80}
```

### Display
```python
{"target": "display", "text": "The room is listening", "style": "calm"}
{"target": "display", "text": "Climax building", "style": "alert"}
```

### Cue-based (MIDI/QLab)
```python
{"target": "audio", "cue_number": 5, "midi_action": "go"}
```

## Wiring a new adapter into the engine

In `src/main.py`, update `wire_engine()` and `run_mock()` / `run_performance()`:

```python
from src.adapters.outputs.real import DMXAdapter

outputs = {
    "lights": DMXAdapter(host="192.168.1.100", port=6454),
    "audio": MIDIAdapter(host="qlab.local", port=53000),
    "display": MockDisplayAdapter(),
}
```

## Real hardware quick reference

| Hardware | Adapter | Protocol |
|----------|---------|----------|
| Generic DMX lighting | `DMXAdapter` | Art-Net over UDP |
| QLab | `MIDIAdapter` or `OSCAdapter` | MSC over UDP / OSC |
| PIR motion sensor | `MotionSensor` | JSON over UDP |
| Lighting console | `OSCAdapter` | OSC |

All adapters use only Python stdlib — no native dependencies.
