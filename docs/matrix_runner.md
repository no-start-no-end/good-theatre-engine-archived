# MatrixRunner and DimensionDriver

Two new layers that make the phase space matrix live and responsive.

## MatrixRunner — PhaseSpace + PerformanceRunner bridged

`MatrixRunner` runs the `PhaseSpace` as the primary performance driver, with `PerformanceRunner` handling canonical phase state, knowledge persistence, and constraint enforcement.

### Modes

**`MATRIX_FIRST`** (default) — PhaseSpace drives all transitions. Push detection happens in `tick()`; `PerformanceRunner` follows.

```python
from src.matrix_runner import MatrixRunner, Mode
from src.performance_matrix import PhaseSpace

runner = MatrixRunner(
    space=space,
    knowledge=knowledge,
    interface=interface,
    decision_engine=decision_engine,
    dimension_driver=driver,
    mode=Mode.MATRIX_FIRST,
)
```

**`SEQUENCE_FIRST`** — `PerformanceRunner`'s linear phase sequence is primary. `PhaseSpace` is kept in sync but does not drive.

```python
runner = MatrixRunner(
    space=space,
    ...
    mode=Mode.SEQUENCE_FIRST,
)
```

### Registering callbacks

```python
runner.on_phase_enter("act_1", lambda s: lights.go("act_1_preset"))
runner.on_phase_enter("act_2", lambda s: audio.go_cue(7))
runner.on_phase_exit("act_1",  lambda s: audio.fade_out_cue(3))
```

Callbacks receive the `PhaseSpace` instance so you can read dimension values:
```python
runner.on_phase_enter("act_2", lambda s: print(f"Energy: {s.get('energy')}"))
```

### Transitions

**Push** (automatic) — detected in `tick()`:
```python
# Energy builds naturally → act_2 triggers automatically
runner.space.set_velocity("energy", 0.1)  # +0.1/sec
while runner.is_running:
    runner.tick()  # fires on_phase_enter("act_2") when energy crosses 0.55
    time.sleep(0.1)
```

**Jump** (explicit) — immediate:
```python
runner.jump("intermission")  # hard cut
```

**Operator override** — human-triggered:
```python
runner.operator_override("outro")  # highest priority
```

### Run loop

```python
runner.start()  # background thread, 10Hz tick

# Or manual tick:
while runner.is_running:
    runner.tick()
    sync_hardware(runner.space.snapshot())
    time.sleep(0.1)
```

### Status

```python
status = runner.status()
print(status["current_region"])   # "act_1"
print(status["current_phase"])    # "act_1"
print(status["space"]["dimensions"]["energy"])  # 0.63
```

---

## DimensionDriver — sensor signals → dimension values

`DimensionDriver` bridges the sensor/adapter layer to the `PhaseSpace`. It maps raw sensor values to dimension values with optional EMA smoothing to avoid jitter.

### Basic mapping

```python
from src.dimension_driver import DimensionDriver

driver = DimensionDriver(space)

# Zigbee PIR → occupancy dimension
driver.map("zigbee.front_pir", "occupancy",
           to_dimension="occupancy", scale=1.0, smoothing=0.3)

# Audio amplitude → energy dimension
driver.map("audio.amplitude", "level",
           to_dimension="energy", scale=0.8, offset=0.1, smoothing=0.5)
```

### In the message bus

```python
# Subscribe driver to the bus
bus.subscribe("zigbee", driver.on_bus_event)
bus.subscribe("audio",  driver.on_bus_event)
```

When a Zigbee message with tag `zigbee.front_pir` and payload `{"occupancy": 1}` arrives:
1. Driver finds the matching rule
2. Applies EMA smoothing
3. Writes `0.3` to the `occupancy` dimension (via `space.set()`)
4. If `occupancy` crosses a region boundary → `tick()` detects push → phase transition!

### Direct push

```python
# For callbacks or non-bus signals
driver.push("midi.knob_1", "value", 0.75)
```

### Disabling sources

```python
driver.disable("zigbee.front_pir")  # pause occupancy feed
driver.enable("zigbee.front_pir")    # resume
```

### Status

```python
print(driver.status())
# {
#   "active_rules": 2,
#   "raw_values": {"audio.amplitude": 0.9},
#   "smoothed": {"audio.amplitude": 0.45},
#   "dimension_snapshot": {"energy": 0.36, "occupancy": 0.3}
# }
```

---

## Example: full show with matrix

```python
from src.performance_matrix import PhaseSpace
from src.matrix_runner import MatrixRunner
from src.dimension_driver import DimensionDriver

# Define the space
space = PhaseSpace()
space.add_dimension("energy",     current=0.2, min=0.0, max=1.0)
space.add_dimension("tempo",      current=60,  min=20, max=140)
space.add_dimension("color_temp", current=3200, min=153, max=6535)

space.add_region("intro", {
    "energy": (0.00, 0.30), "tempo": (40, 70), "color_temp": (2000, 3200),
})
space.add_region("act_1", {
    "energy": (0.30, 0.65), "tempo": (70, 100), "color_temp": (3200, 4800),
})
space.add_region("intermission", {
    "energy": (0.00, 0.25), "tempo": (30, 55), "color_temp": (2400, 3000),
})
space.add_region("act_2", {
    "energy": (0.55, 1.00), "tempo": (90, 140), "color_temp": (4500, 6500),
})
space.add_region("outro", {
    "energy": (0.00, 0.15), "tempo": (20, 40), "color_temp": (2000, 2700),
})

# Wire sensors to dimensions
driver = DimensionDriver(space)
driver.map("zigbee.front_pir", "occupancy", to_dimension="occupancy")
driver.map("audio.amplitude", "level", to_dimension="energy", scale=0.7, smoothing=0.4)
driver.map("midi.tempo", "bpm", to_dimension="tempo", scale=1.0)

# Build runner
runner = MatrixRunner(
    space=space,
    knowledge=knowledge,
    interface=interface,
    decision_engine=decision_engine,
    dimension_driver=driver,
)

# What happens on each phase
runner.on_phase_enter("intro", lambda s: (lights.go("intro_preset"), audio.go_cue(1)))
runner.on_phase_enter("act_1",  lambda s: (lights.go("act_1_full"),  audio.go_cue(3)))
runner.on_phase_enter("act_2",  lambda s: (lights.go("act_2_intense"), audio.go_cue(7)))
runner.on_phase_enter("intermission", lambda s: (lights.go("intermission"), audio.pause_all()))
runner.on_phase_enter("outro",  lambda s: (lights.go("blackout"), audio.stop_all()))

# Register bus subscriptions
bus.subscribe("zigbee", driver.on_bus_event)
bus.subscribe("audio",  driver.on_bus_event)
bus.subscribe("midi",   driver.on_bus_event)

runner.start()
```
