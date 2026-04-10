"""Keyboard input for a live operator using stdlib only."""
from __future__ import annotations

import os
import queue
import select
import sys
import threading
import time

from .base import BaseInputAdapter
from ...core.interface import InterfaceLayer
from ...core.message import Priority, UniversalMessage, human_input

if os.name == "nt":  # pragma: no cover
    import msvcrt
else:  # pragma: no cover
    import termios
    import tty


class KeyboardAdapter(BaseInputAdapter):
    """Translate operator keypresses into universal human_input messages."""

    KEY_BINDINGS = {
        " ": "presence",
        "\n": "applause",
        "\x1b": "emergency_stop",
        "1": "phase_intro",
        "2": "phase_act_1",
        "3": "phase_intermission",
        "4": "phase_act_2",
        "5": "phase_outro",
        "m": "mute_toggle",
        "M": "mute_toggle",
    }

    def __init__(self, interface: InterfaceLayer | None = None):
        self.interface = interface
        self._old_settings = None
        self._enabled = False
        self._queue: queue.Queue[UniversalMessage] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._fd: int | None = None

    def start(self):
        """Enable cbreak mode and start background key capture when possible."""
        if self._enabled:
            return
        self._enabled = True
        if os.name != "nt" and sys.stdin.isatty():  # pragma: no branch
            self._fd = sys.stdin.fileno()
            self._old_settings = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Restore terminal state and stop reading keys."""
        self._enabled = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.2)
        if os.name != "nt" and self._fd is not None and self._old_settings is not None:  # pragma: no branch
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_settings)
        self._fd = None
        self._old_settings = None

    def read(self) -> UniversalMessage | None:
        """Return the next buffered operator message, if any."""
        if not self._enabled:
            return None
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def _listen_loop(self):  # pragma: no cover
        while self._enabled:
            key = self._read_key()
            if key is None:
                time.sleep(0.02)
                continue
            message = self._translate_key(key)
            if message is None:
                continue
            self._queue.put(message)
            if self.interface is not None:
                self.interface.receive(message)

    def _read_key(self) -> str | None:  # pragma: no cover
        if os.name == "nt":
            if not msvcrt.kbhit():
                return None
            key = msvcrt.getwch()
            return "\n" if key == "\r" else key
        if not sys.stdin.isatty():
            return None
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1)
        return None

    def _translate_key(self, key: str) -> UniversalMessage | None:
        action = self.KEY_BINDINGS.get(key)
        if not action:
            return None
        if action == "presence":
            return human_input("keyboard", {"action": "presence", "approved": True}, tags=["keyboard", "presence"])
        if action == "applause":
            return human_input("keyboard", {"action": "applause", "approved": True}, tags=["keyboard", "applause"])
        if action == "emergency_stop":
            return human_input(
                "keyboard",
                {"action": "emergency_stop", "approved": True},
                priority=Priority.CRITICAL,
                tags=["keyboard", "emergency"],
            )
        if action == "mute_toggle":
            return human_input(
                "keyboard",
                {"action": "mute_toggle", "approved": True},
                priority=Priority.HIGH,
                tags=["keyboard", "mute"],
            )
        phase_map = {
            "phase_intro":        "detecting",
            "phase_act_1":        "stabilizing",
            "phase_intermission": "suspended",
            "phase_act_2":        "escalating",
            "phase_outro":        "dispersing",
        }
        phase = phase_map.get(action)
        if phase:
            return human_input(
                "keyboard",
                {"action": "transition", "phase": phase, "approved": True},
                priority=Priority.HIGH,
                tags=["keyboard", "phase"],
            )
        return None
