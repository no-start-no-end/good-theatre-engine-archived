# Running Good Theatre Engine

## Quick start (no hardware needed)

```bash
cd good-theatre-engine
python3 -m src.main --mode mock --log-dir ./logs
```

Mock mode runs with simulated motion, camera, and microphone adapters. No hardware required — all outputs print to the terminal.

## Modes

### `--mode mock`
Simulated sensors, real decision engine and bus. Good for development and rehearsal without equipment.
```bash
python3 -m src.main --mode mock --log-dir ./logs
```

### `--mode cli`
Operator terminal console with live event stream, pattern inspection, phase control, and override injection.
```bash
python3 -m src.main --mode cli --log-dir ./logs
```
Commands: `start`, `stop`, `phase intro|act_1|...`, `energy [0-1]`, `emergency`, `patterns`, `bus`, `inject`, `gate bypass|advisory|mandatory|override`, `quit`

### `--mode dashboard`
Web-based control room at `http://127.0.0.1:8080`. Phase buttons, energy gauge, timeline, event injection form, live SSE feed.
```bash
python3 -m src.main --mode dashboard --log-dir ./logs
```

### `--mode performance`
Full performance run with a cue list config. Requires `--config` pointing to a Python phase config.
```bash
python3 -m src.main --mode performance --config src/default_show.py --log-dir ./logs
```
The built-in `default_show.py` is a 10-cue atmospheric piece. See `README.md` "Writing your first show" for how to write your own.

### `--mode test`
Run the full test suite.
```bash
python3 -m src.main --mode test
```

## Gate modes

Control how human input is weighted:

| Flag | Behaviour |
|------|-----------|
| `--gate bypass` | Everything goes through — use in development |
| `--gate advisory` | System recommends; human overrides via `human_input` |
| `--gate mandatory` | Critical actions need explicit `approved=True` |
| `--gate override` | Only `human_input` messages pass |

## Performance phases

The system runs through five named phases:

```
INTRO → ACT_1 → INTERMISSION → ACT_2 → OUTRO
```

Each phase has:
- A target energy level (0.0–1.0)
- A set of allowed output targets
- A minimum transition duration

Phase configs are defined in a Python file and passed via `--config`.

## Cue lists

Cue lists are Python config files. See `src/default_show.py` for a 10-cue atmospheric opening piece. Each cue has:
- A number (for operator reference)
- A description
- A dict of `{target: params}` — these become `output_command` messages
- An `offset_seconds` for timed firing
- Tags for documentation

See `README.md` "Writing your first show" for a step-by-step guide to creating a new show.

## Keyboard shortcuts (live performance mode)

When running in `performance` mode with a keyboard attached:
- `SPACE` — presence pulse (→ `human_input`)
- `ENTER` — applause
- `1-5` — jump to phase (intro, act_1, intermission, act_2, outro)
- `ESC` — emergency stop
- `M` — mute toggle

## Logs

All events written to `logs/events.jsonl` as JSONL lines. State snapshots to `logs/performance_state.json`. Patterns to `logs/patterns.jsonl`.

## Before a show — pre-flight checklist

```bash
# 1 — Verify tests still pass
python3 -m pytest -q

# 2 — Dry run in mock mode
python3 -m src.main --mode mock --log-dir ./logs
# (let it run 30 seconds, watch for errors, then ESC + q)

# 3 — Dry run with your show file
python3 -m src.main --mode performance --config my_show.py --log-dir ./logs

# 4 — Check the replay
python3 -m src.replay --log-dir ./logs
step 10     # walk through 10 events
q
```

## QLab integration

See `docs/qlab.md` for full setup. Quick version:
- Engine sends OSC to QLab on port 53000
- QLab sends OSC to Engine on port 53001
- In QLab: **Workspace Settings → OSC → outgoing port 53001**

```python
from src.qlab import QLabSender, QLabWatcher
sender = QLabSender(host="qlab.local", port=53000)
watcher = QLabWatcher(sender=sender)
watcher.fire(cue_number=5)   # fires QLab cue 5
```

## Post-show analysis

```bash
# Summary
python3 -m src.analyse analyse ./logs

# Interactive replay
python3 -m src.replay --log-dir ./logs
```

See `docs/replay.md` for full replay console commands.

## Running tests

```bash
python3 -m pytest -q                    # all tests
python3 -m pytest tests/test_cues.py -v # cue system only
python3 -m pytest tests/integration/   # integration tests
```
