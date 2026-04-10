# Architecture

Good Theatre Engine routes everything through one shared message model.

```text
Universal Message Object → Message Bus → Interface Layer → Decision Engine → Output Adapters
                             │
                             → Knowledge Base
                             → Human observers (CLI + dashboard)
```

## Layers

### `src/core/` — Foundational layers
- **`message.py`** — UniversalMessage schema + convenience constructors
- **`bus.py`** — Pub/sub message bus, routing messages to subscribers
- **`interface.py`** — Gate mode enforcement, event logging to JSONL, routing
- **`knowledge.py`** — Persistent state (JSON) + pattern store (JSONL)

### `src/adapters/` — Hardware boundaries

**Inputs** — all inherit `BaseInputAdapter`:
- `mock/` — MockMotion, MockCamera, MockMicrophone for rehearsal
- `real/` — MotionSensor (UDP JSON), KeyboardAdapter for live input
- `keyboard.py` — cbreak-mode key capture for operator overrides

**Outputs** — all inherit `BaseOutputAdapter`:
- `mock/` — MockLight, MockAudio, MockDisplay for testing
- `real/` — DMXAdapter (Art-Net/UDP), MIDIAdapter (MSC/UDP), OSCAdapter
- `osc.py` — OSC for QLab and lighting consoles

### `src/ai/` — Intelligence layer
- **`decision.py`** — Zone-aware decision engine; triad framing + pattern weighting
- **`triads.py`** — Three lenses: impatient_artist, small_dog, robot_perspective
- **`prompts.py`** — Structured prompts for external LLM calls
- **`pattern_learner.py`** — Post-performance log analysis → pattern store

### `src/cues/` — Structured performance control
- **`cues/__init__.py`** — CueList + Cue data model with numbered cues, timing, targets
- **`runner.py`** — Background thread that fires cues on schedule
- **`examples.py`** — 10-cue atmospheric opening piece

### `src/performance.py` — Phase orchestration
- `PerformanceRunner` manages intro / act_1 / intermission / act_2 / outro
- Each phase has target energy, allowed outputs, and minimum duration
- Emergency stop, pause, and resume are first-class

### `src/operators/` — Human interfaces
- **`cli.py`** — Terminal console with live event stream, pattern inspection, gate control
- **`dashboard.py`** — Web dashboard (localhost:8080) with SSE feed, event injection, phase control

## Observability

- Every message is written to `logs/events.jsonl` with trace_id
- State snapshots persisted to `logs/performance_state.json`
- Learned patterns written to `logs/patterns.jsonl`
- CLI live stream shows all bus traffic in colour
- Dashboard SSE pushes state every 3 seconds

## Gate modes

`InterfaceLayer.gate_mode` controls approval:

| Mode | Behaviour |
|------|-----------|
| `bypass` | All messages pass |
| `advisory` | All pass; system recommends, human may override |
| `mandatory` | Critical messages need `approved=True` in payload |
| `override` | Only `human_input` messages pass |

## Message type flow

```
sensor_event     → (bus) → interface → decision → output_command
human_input      → (bus) → interface → [gate check] → decision → output_command
ai_output        → (bus) → interface → routing for display/text
system           → (bus) → interface → logging + timeline
output_command   → (bus) → output adapter handler
```

## Decision pipeline

```
1. INTERPRET  — urgency, energy, movement, text, zone, triad_balance
2. PATTERNS   — fetch learned patterns for this trigger source
3. DECIDE     — select commands weighted by pattern success + triad balance
4. CONSTRAIN  — apply max_volume, min_light_transition, max_light_level
5. GENERATE   — emit UniversalMessage output_command objects
6. LOG        — record pattern outcome to knowledge base
```
