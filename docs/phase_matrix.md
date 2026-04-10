# Phase Space Matrix

The performance engine uses a **multi-dimensional phase space** instead of a linear phase sequence.

## Why a matrix?

A linear sequence (`INTRO → ACT_1 → INTERMISSION → ACT_2 → OUTRO`) is a playback timeline. It tells the engine what to do in order. But theatre is alive — energy shifts continuously, the audience breathes with the show, tension rises and falls.

The phase space matrix models this as a **continuous multi-dimensional space**:

- Each **dimension** is a continuous signal (energy, tempo, color temperature, audio level, motion intensity…)
- Each **phase/region** occupies a hyper-rectangle defined by boundary ranges on every dimension
- The engine tracks all dimensions simultaneously and detects when the state vector enters a new region

This means:
- Phases can **overlap** in some dimensions but differ in others
- Transitions happen either by **pushing** (values cross a boundary) or by **jumping** (explicit call)
- The system can be driven by sensor input — motion, sound, biometric — not just a clock

## Core concepts

### Dimension

A named continuous axis with a current value, min/max bounds, and an optional velocity (rate of change per second).

```python
space.add_dimension("energy",     current=0.2, min=0.0, max=1.0)
space.add_dimension("tempo",      current=60,  min=20, max=140)
space.add_dimension("color_temp", current=3200, min=153, max=6535)  # Kelvin
```

Values are set directly or driven by velocity:

```python
space.set("energy", 0.8)          # direct value
space.set_velocity("energy", 0.1) # +0.1 per second (e.g. slow build)
```

### Region (Phase)

A named region in the space, defined by `(min, max)` boundary ranges on each dimension:

```python
space.add_region("intro", {
    "energy":     (0.00, 0.30),
    "tempo":      (40,   70),
    "color_temp": (2000, 3200),
})
space.add_region("act_1", {
    "energy":     (0.30, 0.65),
    "tempo":      (70,   100),
    "color_temp": (3200, 4800),
})
space.add_region("intermission", {
    "energy":     (0.00, 0.25),
    "tempo":      (30,   55),
    "color_temp": (2400, 3000),
})
```

A state vector is "in" a region only when **all** its dimension values are within that region's boundary ranges simultaneously.

### Push (automatic transition)

When dimension values naturally move the state vector into a new region — e.g. energy builds from 0.28 to 0.35 — the engine detects this and fires the transition automatically:

```python
def on_act_1_enter(space):
    print("Entering Act 1 — energy rising!")
    lights.go("act_1_preset")
    audio.go_cue(5)

space.on_enter("act_1", on_act_1_enter)

# In the run loop — tick drives the space continuously
while running:
    space.tick(delta_seconds=0.1)  # advances all velocities by 0.1s
    # push detection happens automatically
```

### Jump (explicit transition)

Explicit override — go to any region immediately, bypassing boundary detection:

```python
space.jump("intermission")  # hard cut to intermission
```

Useful for: operator interventions, emergency redirects, audience-triggered events.

### Callbacks

Register callbacks for region entry/exit:

```python
space.on_enter("act_2", lambda s: lights.go("act_2_full"))
space.on_exit("act_1",  lambda s: audio.fade_out_cue(3))
```

## Run loop integration

```python
from src.performance_matrix import PhaseSpace

space = PhaseSpace()
# ... configure dimensions and regions ...

# In your main run loop (e.g. every 100ms):
def tick():
    now = time.time()
    delta = now - last_tick
    last_tick = now

    new_region = space.tick(delta_seconds=delta)
    if new_region:
        # Push transition occurred — new_region.name tells you which
        interface.notify_phase_change(new_region.name)

    # Sync other systems with current dimension values
    energy = space.get("energy")
    tempo  = space.get("tempo")
    sync_lights(energy, tempo)
```

## Dimension-driven vs time-driven

The matrix decouples **what** happens from **when**. Time-driven: cue 7 fires at 4:32. Dimension-driven: the energy dimension crosses 0.65, so we enter Act 2.

Both can coexist. Use:
- **Time** for hard theatrical synchronisation (the bow must happen after the last line)
- **Dimensions** for organic, responsive orchestration (tension follows the audience)

## API reference

| Method | Description |
|--------|-------------|
| `add_dimension(name, current, min, max)` | Add a continuous axis |
| `set(name, value)` | Set a dimension's current value |
| `get(name)` | Get a dimension's current value |
| `set_velocity(name, velocity)` | Set the rate of change (per second) |
| `snapshot()` | Dict of all current dimension values |
| `add_region(name, boundaries)` | Define a phase region |
| `on_enter(name, callback)` | Register entry callback |
| `on_exit(name, callback)` | Register exit callback |
| `tick(delta_seconds)` | Advance all velocities; detect and fire pushes |
| `jump(region_name)` | Immediate explicit transition |
| `current_region()` | Name of the currently active region |
| `status()` | Full snapshot of space state |
