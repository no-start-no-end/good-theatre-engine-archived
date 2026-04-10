# QLab Integration

[QLab](https://figure53.com/qlab/) is the standard theatrical media server for audio, video, and lighting cue control on macOS. This module bridges the Good Theatre Engine to QLab via OSC.

## Architecture

```
Engine → QLabSender (UDP/OSC) ──→ QLab (port 53000)
QLab → OSCListener (UDP port 53001) → Engine message bus
```

QLab sends OSC on port 53001 by default (configurable per workspace). The Engine listens there and converts QLab's cue life-cycle messages (`/cue/n/go`, `/cue/n/stop`, `/cue/n/update`) into structured events on the internal bus.

## Quick Start

```python
from src.qlab import QLabSender, QLabWatcher
from src.osc_listener import OSCListener

# Fire a QLab cue from the engine
sender = QLabSender(host="192.168.1.100", port=53000)
sender.cue_go(cue_number=5)

# Keep engine + QLab in sync (prevents double-firing)
watcher = QLabWatcher(sender=sender)
watcher.fire(cue_number=5)   # Only fires if not already running
```

## QLabSender

Send OSC commands to QLab over UDP.

```python
sender = QLabSender(host="qlab.local", port=53000)

sender.cue_go(cue_number)     # Fire a cue
sender.cue_stop(cue_number)    # Stop a cue
sender.cue_pause(cue_number)   # Pause a cue
sender.cue_load(cue_number)   # Pre-load a cue
sender.all_stop()              # Stop all running cues
sender.panic()                 # Hard stop — emergency fade out
```

## QLabWatcher

Tracks which QLab cues are currently running, preventing accidental double-fires.

```python
watcher = QLabWatcher(sender=sender)
watcher.fire(cue_number=7)           # Sends /cue/7/go
watcher.fire(cue_number=7)           # No-op — already running
watcher.on_cue_complete(cue_number=7) # Call when cue finishes
watcher.status()                     # {"active_cues": [], "count": 0}
```

## OSCListener

Receives OSC from QLab (or any OSC sender) and injects structured messages into the Engine's message bus.

```python
from src.osc_listener import OSCListener
from src.core.bus import MessageBus

bus = MessageBus()
listener = OSCListener(host="0.0.0.0", port=53001)

def handle_cue(msg):
    cue_num = msg.payload["cue_number"]
    action = msg.payload["osc_action"]
    print(f"QLab cue {cue_num} {action}")

listener.on("/cue/*/go", handle_cue)
listener.start()

# In your run loop:
msg = listener.read()
if msg:
    bus.publish(msg)
```

## Wire QLab ↔ Engine in a Show

```python
# In your show file (e.g. my_show.py)
from src.main import create_engine
from src.qlab import QLabSender, QLabWatcher

engine = create_engine(mode="cli")
bus = engine["bus"]
qlab_sender = QLabSender(host="qlab.local", port=53000)
qlab_watcher = QLabWatcher(sender=qlab_sender)

# When firing engine cue 5, also fire QLab cue 10
cue_runner = engine["cue_runner"]
cue_runner.on_cue_fire = lambda cue: qlab_watcher.fire(cue_number=10)
```

## Network Setup

| Service | Default Port | Protocol |
|---------|-------------|----------|
| QLab workspace | 53000 | UDP (OSC out) |
| Engine OSCListener | 53001 | UDP (OSC in) |
| QLab broadcast | 53002 | UDP |

Both machines must be on the same network. Set static IPs or use Bonjour/Avahi hostnames.

## QLab Workspace OSC Settings

In QLab: **Workspace Settings → OSC**
- Enable OSC listener
- Set outgoing port to `53001` (or match `OSCListener.port`)
- Enable: "/cue/{cue number}/{action}"

## Health Check

```python
from src.qlab import qlab_heartbeat

if qlab_heartbeat(host="qlab.local"):
    print("QLab is reachable")
else:
    print("QLab not responding")
```
