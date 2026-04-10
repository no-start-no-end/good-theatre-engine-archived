# Replay Console

Interactive step-through debugger for performance logs. Load an event stream, step forward and backward, filter by type or source, annotate interesting events, and export a curated highlight reel.

## Usage

```bash
python3 -m src.replay --log-dir ./logs
```

## Commands

| Command | Description |
|---------|-------------|
| `step [n]` | Move forward n events (default: 1) |
| `back [n]` | Move backward n events (default: 1) |
| `goto <idx>` | Jump to event at filtered index |
| `show [n]` | Show n events around current position |
| `filter [type] [source-substring]` | Filter by message type and/or source. Use `_` to keep existing filter. |
| `tag <text>` | Annotate current event |
| `info` | Show event statistics by type |
| `save <path>` | Export annotated events to JSON |
| `help` | Show all commands |
| `q` | Quit |

## Examples

```bash
# Start replay
python3 -m src.replay --log-dir ./logs

# Filter to only output commands
> filter output_command _

# Show 10 events around current position
> show 10

# Tag an interesting event
> tag check-this-cue-fire-timing

# Export all annotations
> save annotated.json
```

## Filter Syntax

```
filter [type] [source]
```

- `type`: Message type (e.g. `sensor_event`, `output_command`, `human_input`, `phase_change`)
- `source`: Substring to match in the source field (e.g. `keyboard`, `dmx`, `qlab`)
- Use `_` to keep the current filter value

Examples:
```
filter sensor_event _         # All sensor events
filter _ qlab                # Anything from QLab
filter output_command lights # Output commands to lights
```

## Output Format

Each event shows:
```
>>> [00001] 2026-04-09T10:00:01 (a1b2c3d4) output_command        engine.lights             {"cue": 5, "action": "on"} # my annotation
```

- `>>>` marks the current position
- `[#####]` is the absolute event index
- `(trace)` is the 8-char trace ID for cross-referencing
- `type` and `source` columns
- Full JSON payload
- `# annotation` if tagged

## DLQ Integration

After a performance, replay the dead-letter queue:

```python
from src.cues.runner import CueRunner

runner = CueRunner(...)
# ... after a run ...
dlq = runner.dlq_status()
for item in dlq["items"]:
    print(f"Cue {item['cue']} target={item['target']}: {item['error']}")

# Replay item 0
runner.replay_dlq_item(0)
```
