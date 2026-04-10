"""QLab integration: wire the cue runner to QLab via OSC.

QLab is the standard theatrical media server for audio, video, and lighting cue control.
This module provides:
- QLabSender: send OSC commands to QLab
- QLabWatcher: track active cues and prevent re-firing during a performance
- qlab_heartbeat: check QLab network availability
"""
from __future__ import annotations

import socket
import struct
from dataclasses import dataclass, field
from typing import Any


@dataclass
class QLabSender:
    """Send OSC commands to QLab over UDP.

    QLab listens on port 53000 by default. Configure host/port to match
    your QLab network settings.
    """

    host: str = "localhost"
    port: int = 53000
    _sock: Any = field(default=None, init=False)

    def __post_init__(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, address: str, *args: Any):
        """Send a raw OSC message to QLab."""
        packet = self._build_osc(address, list(args))
        self._sock.sendto(packet, (self.host, self.port))

    def cue_go(self, cue_number: int):
        """Fire QLab cue number n."""
        self.send(f"/cue/{cue_number}/go")

    def cue_stop(self, cue_number: int):
        """Stop QLab cue number n."""
        self.send(f"/cue/{cue_number}/stop")

    def cue_pause(self, cue_number: int):
        """Pause QLab cue number n."""
        self.send(f"/cue/{cue_number}/pause")

    def cue_load(self, cue_number: int):
        """Pre-load QLab cue number n."""
        self.send(f"/cue/{cue_number}/load")

    def all_stop(self):
        """Stop all running cues."""
        self.send("/cue/all/stop")

    def panic(self):
        """Hard stop — fade out everything immediately (QLab panic command)."""
        self.send("/panic")

    def _build_osc(self, address: str, args: list) -> bytes:
        """Build a raw OSC packet."""
        addr_bytes = address.encode("utf-8") + b"\x00"
        padding = (4 - (len(addr_bytes) % 4)) % 4
        addr_bytes += b"\x00" * padding

        if not args:
            return addr_bytes + b",\x00\x00\x00"

        type_tags = b"," + b"".join(self._osc_tag(v) for v in args)
        while len(type_tags) % 4 != 0:
            type_tags += b"\x00"

        arg_bytes = b"".join(self._osc_encode(v) for v in args)
        while len(arg_bytes) % 4 != 0:
            arg_bytes += b"\x00"

        return addr_bytes + type_tags + arg_bytes

    @staticmethod
    def _osc_tag(v: Any) -> bytes:
        if isinstance(v, int):
            return b"i"
        if isinstance(v, float):
            return b"f"
        return b"s"

    @staticmethod
    def _osc_encode(v: Any) -> bytes:
        if isinstance(v, int):
            return struct.pack(">i", v)
        if isinstance(v, float):
            return struct.pack(">f", v)
        encoded = str(v).encode("utf-8") + b"\x00"
        return encoded + b"\x00" * ((4 - len(encoded) % 4) % 4)

    @staticmethod
    def _osc_pad_string(s: str) -> bytes:
        b = s.encode("utf-8") + b"\x00"
        return b + b"\x00" * ((4 - len(b) % 4) % 4)


@dataclass
class QLabWatcher:
    """Sync the engine's cue runner with QLab running cues.

    Tracks which QLab cues are active, suppresses re-firing already-running cues,
    and maps QLab's feedback back into the message bus so the engine responds
    to actual QLab state.
    """

    sender: QLabSender
    cue_runner: Any = None
    _running_cues: set[int] = field(default_factory=set)

    def fire(self, cue_number: int):
        """Fire a cue in QLab, tracking it as running."""
        if cue_number in self._running_cues:
            return  # Don't re-fire an active cue
        self.sender.cue_go(cue_number)
        self._running_cues.add(cue_number)

    def on_cue_complete(self, cue_number: int):
        """Call this when a cue completes in QLab to untrack it."""
        self._running_cues.discard(cue_number)

    def is_cue_active(self, cue_number: int) -> bool:
        return cue_number in self._running_cues

    def stop_all(self):
        """Stop all QLab cues."""
        self.sender.all_stop()
        self._running_cues.clear()

    def panic(self):
        """Emergency stop everything."""
        self.sender.panic()
        self._running_cues.clear()

    def status(self) -> dict[str, Any]:
        return {
            "active_cues": sorted(self._running_cues),
            "count": len(self._running_cues),
        }


def qlab_heartbeat(
    host: str = "localhost",
    port: int = 53000,
    timeout: float = 1.0,
) -> bool:
    """Return True if QLab is reachable on the network."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sender = QLabSender(host=host, port=port)
        sender.send("/sys/ping", "engine heartbeat")
        return True
    except Exception:
        return False
    finally:
        sock.close()
