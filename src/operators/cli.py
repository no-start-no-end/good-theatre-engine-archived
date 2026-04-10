"""Terminal operator interface with phase control, live event stream, and cue management."""
from __future__ import annotations

import json
import os
import select
import sys
import time
from collections import deque

from ..core.interface import InterfaceLayer
from ..core.knowledge import KnowledgeBase
from ..core.message import MessageType, Priority, UniversalMessage, human_input, sensor_event


class CLI:
    """Terminal interface for operating the system during rehearsal or show."""

    COMMANDS = {
        "start": "Start performance",
        "stop": "Stop performance",
        "status": "Show current state",
        "phase": "Transition to a phase (phase intro|act_1|intermission|act_2|outro)",
        "energy": "Show or set target energy (energy [0.0-1.0])",
        "emergency": "Hard stop all outputs",
        "timeline": "Show recent events (timeline [N])",
        "inject": "Inject a test message (inject <type> <source> <payload_json>)",
        "patterns": "Show learned patterns",
        "override": "Send human override (override <target> <value>)",
        "gate": "Set gate mode (gate bypass|advisory|mandatory|override)",
        "knowledge": "Show current knowledge state",
        "bus": "Show recent messages on the bus",
        "cues": "List cue list (if loaded)",
        "fire": "Fire cue number (fire <n>)",
        "cue_status": "Show cue runner status",
        "stream": "Toggle live message stream",
        "help": "Show commands",
        "quit": "Exit",
    }

    COLORS = {
        "cyan": "\033[96m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "red": "\033[91m",
        "magenta": "\033[95m",
        "reset": "\033[0m",
        "bold": "\033[1m",
    }

    def __init__(self, interface: InterfaceLayer, knowledge: KnowledgeBase, performance_runner=None, cue_runner=None):
        self.interface = interface
        self.knowledge = knowledge
        self.performance_runner = performance_runner
        self.cue_runner = cue_runner
        self.recent_messages: deque[dict] = deque(maxlen=80)
        self.stream_enabled = True
        self.running = False
        self.interface.bus.subscribe_all(self._capture)

    def _capture(self, message: UniversalMessage):
        self.recent_messages.append(message.to_dict())
        if self.stream_enabled:
            print(self._color("cyan", f"[{message.type.value}] {message.source} -> {json.dumps(message.payload)}"))

    def _color(self, name: str, text: str) -> str:
        return f"{self.COLORS[name]}{text}{self.COLORS['reset']}"

    def _clear(self):
        print("\033[2J\033[H", end="")

    def _show_status(self):
        state = self.knowledge.load_state()
        print(self._color("bold", "GOOD THEATRE ENGINE"))
        print(self._color("green", f"phase={state.phase} energy={state.energy_level:.2f} engagement={state.audience_engagement:.2f} gate={self.interface.gate_mode}"))
        if self.performance_runner:
            print(self._color("yellow", f"phase_timer={self.performance_runner.phase_runtime():.1f}s runtime={self.performance_runner.performance_runtime():.1f}s"))
        allowed = state.constraints.get("allowed_outputs", [])
        print(self._color("magenta", f"allowed_outputs={allowed or 'all'}"))

        if self.cue_runner:
            cues = self.cue_runner.cue_list
            print(self._color("cyan", f"\n=== CUE LIST: {cues.name} ==="))
            print(self._color("yellow", f"total={len(cues.all())} fired={len(cues._fired)} pending={len(cues.pending())}"))
            for c in cues.all():
                marker = self._color("green", "✓") if cues.is_fired(c.number) else self._color("red", "○")
                print(f"  {marker} [{c.number:03d}] {c.description}")

    def run(self):
        self.running = True
        last_status = 0.0
        while self.running:
            if time.time() - last_status > 5:
                self._clear()
                self._show_status()
                print(self._color("yellow", "Press ENTER on empty line to toggle live stream. Type 'help' for commands."))
                last_status = time.time()
            print("> ", end="", flush=True)
            ready, _, _ = select.select([sys.stdin], [], [], 5)
            if not ready:
                continue
            line = sys.stdin.readline()
            if line == "\n":
                self.stream_enabled = not self.stream_enabled
                print(self._color("yellow", f"Live stream {'enabled' if self.stream_enabled else 'muted'}"))
                continue
            if not line:
                break
            self.handle_command(line.strip())

    def handle_command(self, line: str):
        if not line:
            return
        parts = line.split(" ", 3)
        command = parts[0]
        if command == "quit":
            self.running = False
        elif command == "help":
            print(json.dumps(self.COMMANDS, indent=2))
        elif command == "start":
            if self.performance_runner:
                self.performance_runner.start()
            else:
                state = self.knowledge.load_state()
                state.phase = "running"
                self.knowledge.save_state(state)
            print(self._color("green", "Performance started"))
        elif command == "stop":
            if self.performance_runner:
                self.performance_runner.end()
            else:
                state = self.knowledge.load_state()
                state.phase = "stopped"
                self.knowledge.save_state(state)
            print(self._color("red", "Performance stopped"))
        elif command == "status":
            self._show_status()
        elif command == "phase" and len(parts) > 1:
            if self.performance_runner:
                self.performance_runner.handle_operator_message(human_input("cli.phase", {"action": "transition", "phase": parts[1], "approved": True}, priority=Priority.HIGH))
            else:
                state = self.knowledge.load_state()
                state.phase = parts[1]
                self.knowledge.save_state(state)
            print(self._color("green", f"Transitioned to {parts[1]}"))
        elif command == "energy":
            state = self.knowledge.load_state()
            if len(parts) > 1:
                state.energy_level = max(0.0, min(1.0, float(parts[1])))
                self.knowledge.save_state(state)
            print(self._color("yellow", f"Target energy {state.energy_level:.2f}"))
        elif command == "emergency":
            if self.performance_runner:
                self.performance_runner.emergency_stop()
            else:
                self.interface.receive(human_input("cli.emergency", {"action": "emergency_stop", "approved": True}, priority=Priority.CRITICAL))
            print(self._color("red", "Emergency stop triggered"))
        elif command == "timeline":
            count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
            print(json.dumps(list(self.recent_messages)[-count:], indent=2))
        elif command == "patterns":
            print(json.dumps(self.knowledge.get_context()["recent_patterns"], indent=2))
        elif command == "knowledge":
            print(json.dumps(self.knowledge.get_context(), indent=2))
        elif command == "bus":
            print(json.dumps(list(self.recent_messages), indent=2))
        elif command == "stream":
            self.stream_enabled = not self.stream_enabled
            print(self._color("yellow", f"Live stream {'enabled' if self.stream_enabled else 'muted'}"))
        elif command == "gate" and len(parts) > 1:
            self.interface.set_gate_mode(parts[1])
            print(self._color("yellow", f"Gate mode set to {parts[1]}"))
        elif command == "override" and len(parts) > 2:
            msg = human_input("cli.override", {"target": parts[1], "value": parts[2], "approved": True})
            self.interface.receive(msg)
        elif command == "inject" and len(parts) == 4:
            msg_type, source, payload_json = parts[1], parts[2], parts[3]
            payload = json.loads(payload_json)
            if msg_type == MessageType.HUMAN_INPUT.value:
                msg = human_input(source, payload)
            else:
                msg = sensor_event(source, payload)
            self.interface.receive(msg)
        elif command == "cues":
            if not self.cue_runner:
                print(self._color("red", "No cue list loaded"))
            else:
                self._show_cues()
        elif command == "fire" and len(parts) > 1:
            if not self.cue_runner:
                print(self._color("red", "No cue runner loaded"))
            else:
                try:
                    n = int(parts[1])
                    self.cue_runner.jump_to(n)
                    print(self._color("green", f"Fired cue {n}"))
                except Exception as e:
                    print(self._color("red", f"Error: {e}"))
        elif command == "cue_status":
            if not self.cue_runner:
                print(self._color("red", "No cue runner loaded"))
            else:
                print(json.dumps(self.cue_runner.status(), indent=2))
        else:
            print(self._color("red", f"Unknown command: {command}"))

    def _show_cues(self):
        cues = self.cue_runner.cue_list
        print(self._color("bold", f"\n=== CUE LIST: {cues.name} ==="))
        for c in cues.all():
            marker = self._color("green", "✓") if cues.is_fired(c.number) else self._color("dim", "○")
            targets = ", ".join(f"{k}" for k in c.targets.keys())
            print(f"  {marker} [{c.number:03d}] {c.description} → {targets}")
        print(self._color("yellow", f"\nfired={len(cues._fired)} pending={len(cues.pending())}"))
