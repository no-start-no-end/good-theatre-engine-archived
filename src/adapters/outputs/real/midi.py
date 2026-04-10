"""MIDI Show Control adapter for theatrical audio — pure stdlib UDP."""
from __future__ import annotations

import socket
import struct
from dataclasses import dataclass, field
from typing import Any

from .base import BaseOutputAdapter
from ....core.message import UniversalMessage


@dataclass
class MIDIAdapter(BaseOutputAdapter):
    """Send MIDI Show Control (MSC) commands to QLab or other MSC receivers.

    MSC General is the standard theatrical control protocol. This adapter
    uses MSC over UDP (QTCP) — no physical MIDI port needed.
    """

    host: str = "localhost"
    port: int = 53000    # QLab default UDP
    device_id: int = 0   # 0=broadcast, 1-16=specific device
    _sent: list[dict[str, Any]] = field(default_factory=list)
    _sock: Any = field(default=None, init=False)

    def __post_init__(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def cue(self, cue_number: int, action: str = "go"):
        """Fire a QLab cue by number (1-65535)."""
        command_code = {
            "go": 1, "stop": 2, "resume": 3,
            "pause": 4, "reset": 5, "load": 6,
        }.get(action.lower(), 1)

        # MSC over UDP — stripped sysex format QLab accepts
        device_id = self.device_id & 0x0F
        status_byte = 0xF0 | device_id
        msg_id = 0x02  # General category
        command_format = command_code & 0x7F

        # Cue number as 2-byte big-endian
        cue_bytes = struct.pack(">H", cue_number & 0xFFFF)
        list_byte = b"\x00"  # list 0

        packet = bytes([
            status_byte, 0x02, msg_id, command_format,
        ]) + cue_bytes + list_byte

        self._sock.sendto(packet, (self.host, self.port))
        self._sent.append({"cue": cue_number, "action": action})

    def send(self, message: UniversalMessage):
        """Interpret a UniversalMessage as MSC commands."""
        payload = message.payload
        action = payload.get("action", "")
        target = payload.get("target", "")

        if payload.get("cue_number") is not None:
            self.cue(int(payload["cue_number"]), str(payload.get("midi_action", action or "go")))
        elif action in {"go", "stop", "resume", "pause", "reset", "load"}:
            self.cue(int(payload.get("cue", payload.get("cue_number", 1))), action)
        elif target == "midi":
            # Raw MIDI: note, velocity, channel
            self._send_midi_note(
                int(payload.get("channel", 1)),
                int(payload.get("note", 60)),
                int(payload.get("velocity", 80)),
            )

    def _send_midi_note(self, channel: int, note: int, velocity: int):
        """Send a raw MIDI note-on over UDP (for testing without hardware)."""
        status = 0x90 | ((channel - 1) & 0x0F)
        packet = bytes([status, note & 0x7F, velocity & 0x7F])
        self._sock.sendto(packet, (self.host, self.port))
        self._sent.append({"type": "note", "channel": channel, "note": note, "velocity": velocity})

    def status(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "device_id": self.device_id,
            "sent_count": len(self._sent),
            "last": self._sent[-1] if self._sent else None,
        }
