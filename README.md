# Good Theatre Engine

**A runnable, observable AI theatre orchestration system.**

Orchestrates live theatrical performances — routing signals from sensors and human operators through a universal message bus, applying learned patterns and triad-decision logic, and sending commands to lights, audio, video, and display systems.

Pure Python stdlib. No native dependencies. Fully mockable for development.

---

## What you need

| Requirement | Detail |
|-------------|--------|
| Python | 3.9+ |
| OS | macOS, Linux |
| Hardware | Optional — everything works in mock mode |

---

## Setup (60 seconds from zero)

```bash
# 1 — Clone
git clone https://github.com/no-start-no-end/good-theatre-engine.git
cd good-theatre-engine

# 2 — Run in mock mode (no hardware needed)
python3 -m src.main --mode mock --log-dir ./logs
```

You should see the operator terminal start up with live event output. Hit `q` to quit.

---

## Modes — choose what fits your setup

### Mock mode — no hardware
```bash
python3 -m src.main --mode mock --log-dir ./logs
```
Generates fake sensor events. All output goes to the terminal. Perfect for writing cues and testing logic.

### Operator terminal
```bash
python3 -m src.main --mode cli --log-dir ./logs
```
Live event stream, keyboard shortcuts, phase control, pattern view. Designed for a show operator running a real performance.

### Web dashboard
```bash
python3 -m src.main --mode dashboard --log-dir ./logs
# Then open: http://127.0.0.1:8080
```
Phase buttons, energy gauge, cue list, event injection. For directors and creative teams watching from off-stage.

### Full performance run
```bash
python3 -m src.main --mode performance --config src/default_show.py --log-dir ./logs
```
Runs the built-in 10-cue example show from start to finish through all phases.

### Run tests
```bash
python3 -m pytest -q
```

---

## Keyboard shortcuts (live performance)

| Key | Action |
|-----|--------|
| `SPACE` | Presence pulse |
| `ENTER` | Applause |
| `1` | Jump to INTRO |
| `2` | Jump to ACT_1 |
| `3` | Jump to INTERMISSION |
| `4` | Jump to ACT_2 |
| `5` | Jump to OUTRO |
| `M` | Mute toggle |
| `ESC` | Emergency stop |
| `q` | Quit |

---

## Gate modes — who is in charge

The gate mode determines whether the system acts on its own or waits for human approval.

```bash
--gate bypass     # Everything goes through (development)
--gate advisory   # System recommends; human can override
--gate mandatory  # Critical actions need explicit approval
--gate override   # Only human commands pass
```

---

## Writing your first show

### Step 1 — Create a cue list

```python
# my_show.py
from src.cues import CueList, Cue, CueType

cue_list = CueList("My First Show")

# add_go(number, name, targets, offset_seconds=0)
cue_list.add_go(1, "House lights fade in",   {"lights": {"value": 0.8}},  offset_seconds=0)
cue_list.add_go(2, "Opening sound",          {"audio": {"volume": 0.6}},  offset_seconds=3)
cue_list.add_go(3, "Spotlight",              {"lights": {"channel": 3, "value": 1.0}}, offset_seconds=8)
cue_list.add_go(4, "Musicians enter",        {"audio": {"volume": 0.9}},   offset_seconds=12)
cue_list.add_go(5, "Full stage",             {"lights": {"value": 1.0}, "audio": {"volume": 1.0}}, offset_seconds=18)
```

### Step 2 — Run it

```bash
python3 -m src.main --mode performance --config my_show.py --log-dir ./logs
```

### Step 3 — Watch the replay

```bash
python3 -m src.replay --log-dir ./logs
```

At the `>` prompt:
```
step        # advance one event
step 5      # advance 5 events
back        # go back one event
filter output_command _   # only show output commands
tag this-cue-is-off     # annotate current event
save highlights.json    # export annotations
q
```

---

## Integrating with QLab

QLab is the standard macOS media server for theatrical audio/video/lighting cue control. The engine speaks to QLab over OSC.

### Network setup

Both machines must be on the same network. Set static IPs or use Bonjour hostnames.

| Direction | Port | Protocol |
|-----------|------|----------|
| Engine → QLab | 53000 | UDP/OSC |
| QLab → Engine | 53001 | UDP/OSC |

In QLab: **Workspace Settings → OSC**
- Enable OSC listener
- Set outgoing port to `53001`

### Fire QLab cues from the engine

```python
from src.qlab import QLabSender

sender = QLabSender(host="qlab.local", port=53000)
sender.cue_go(cue_number=5)   # fires QLab cue 5
sender.cue_stop(cue_number=3) # stops QLab cue 3
sender.panic()                # hard stop everything
```

### Keep engine + QLab in sync

```python
from src.qlab import QLabSender, QLabWatcher

sender = QLabSender(host="qlab.local", port=53000)
watcher = QLabWatcher(sender=sender)

watcher.fire(cue_number=5)  # fires — but won't double-fire if already running
# When the cue completes in QLab:
watcher.on_cue_complete(cue_number=5)
```

### Receive QLab events in the engine

```python
from src.osc_listener import OSCListener

listener = OSCListener(host="0.0.0.0", port=53001)
listener.on("/cue/*/go", lambda msg: print(f"Cue {msg.payload['cue_number']} fired!"))
listener.start()

# In your run loop:
msg = listener.read()
if msg:
    bus.publish(msg)
```

See `docs/qlab.md` for full wiring examples.

---

## Integrating real hardware

### DMX lighting (e.g., ENTTEC DMX USB Pro, Blackmagic ATEM)
```python
from src.adapters.outputs.real import DMXAdapter

lights = DMXAdapter(host="192.168.1.100", port=6454)
lights.receive(output_command("lights", {"channel": 1, "value": 255}))
```

### MIDI Show Control (e.g., QLab, RESOLUTE)
```python
from src.adapters.outputs.real import MIDIAdapter

audio = MIDIAdapter(host="qlab.local", port=53000)
audio.receive(output_command("audio", {"msc_command": "GO", "cue": 5}))
```

### Motion sensors (PIR via UDP JSON)
```python
from src.adapters.inputs.real import MotionSensor

motion = MotionSensor(host="0.0.0.0", port=9001)
```

See `docs/adapters.md` for payload conventions and protocol details.

---

## Log analysis tools

```bash
# Replay events interactively
python3 -m src.replay --log-dir ./logs

# Performance summary
python3 -m src.analyse analyse ./logs

# Last 50 events
python3 -m src.analyse replay ./logs --limit 50

# Filter by message type
python3 -m src.analyse replay ./logs --type output_command
```

---

## Project structure

```
src/
├── main.py                  # Entry point — picks mode
├── cues/
│   ├── __init__.py         # Cue, CueList, CueType
│   ├── runner.py           # CueRunner with retry + DLQ
│   └── builder.py           # Fluent show builder
├── core/
│   ├── message.py          # UniversalMessage schema
│   ├── bus.py              # Pub/sub message bus
│   ├── interface.py        # Gate + event logging
│   ├── knowledge.py        # Persistent state + patterns
│   └── error_log.py        # Structured error log
├── ai/
│   ├── decision.py          # Zone-aware decision engine
│   ├── triads.py           # Three perspective lenses
│   ├── prompts.py          # LLM integration prompts
│   └── pattern_learner.py  # Post-run pattern analysis
├── adapters/
│   ├── inputs/             # Sensor + operator input adapters
│   └── outputs/           # Light, audio, display output adapters
├── operators/
│   ├── cli.py              # Terminal operator console
│   └── dashboard.py        # Web dashboard (:8080)
├── performance.py          # Phase orchestration (sequence mode)
├── performance_matrix.py  # Phase space matrix (dimensions, regions, push/jump)
├── matrix_runner.py          # Bridge: PhaseSpace + PerformanceRunner
├── dimension_driver.py      # Sensor signals → dimension values
├── qlab.py                 # QLab OSC bridge
├── osc_listener.py        # OSC input receiver
├── replay.py               # Interactive event replay
├── analyse.py              # Post-run analysis CLI
└── default_show.py        # 10-cue example show

docs/
├── run.md                  # Operational run guide
├── adapters.md             # Hardware integration reference
├── qlab.md                 # QLab integration guide
├── replay.md               # Replay console reference
├── phase_matrix.md         # Phase space matrix architecture
└── matrix_runner.md          # MatrixRunner + DimensionDriver guide
```

---

## Design principles

| Principle | What it means |
|-----------|---------------|
| **Message object is sacred** | All communication through UniversalMessage |
| **Adapters are disposable** | Swap any adapter without touching core |
| **Knowledge is persistent** | Every performance teaches the system |
| **Human authority is explicit** | Gate modes are always clear |
| **Trace everything** | Replay and debug always possible |
| **Graceful degradation** | A failed DMX cue doesn't stop audio |

---

## Running tests

```bash
# All tests
python3 -m pytest -q

# Specific file
python3 -m pytest tests/test_cues.py -v

# With coverage
python3 -m pytest --cov=src --cov-report=term-missing
```

---

*For architecture deep-dives and operational run guides, see `docs/`.
