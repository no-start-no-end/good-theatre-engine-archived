"""OSC adapter for theatre equipment using UDP and stdlib only."""
from __future__ import annotations

import socket
import struct
from dataclasses import dataclass, field
from typing import Any

from .base import BaseOutputAdapter
from ...core.message import UniversalMessage


@dataclass
class OSCAdapter(BaseOutputAdapter):
    """Send OSC packets to QLab or lighting consoles."""

    host: str = "localhost"
    port: int = 53000
    sent_messages: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, message_or_address: UniversalMessage | str, *args: Any):
        """Send a UniversalMessage or a raw OSC address with arguments."""
        if isinstance(message_or_address, UniversalMessage):
            self._send_from_message(message_or_address)
            return
        packet = self._build_message(message_or_address, list(args))
        self._sock.sendto(packet, (self.host, self.port))
        self.sent_messages.append({"address": message_or_address, "arguments": list(args)})

    def cue(self, cue_number: int, action: str = "go"):
        """Control a cue, for example /cue/12/go."""
        self.send(f"/cue/{cue_number}/{action}")

    def light(self, channel: int, value: float):
        """Set a DMX channel level, normalized 0.0-1.0."""
        self.send(f"/dmx/{channel}", max(0.0, min(1.0, value)))

    def fade(self, channel: int, target: float, duration: float):
        """Fade a DMX channel to a target value over a duration."""
        self.send(f"/dmx/{channel}/fade", max(0.0, min(1.0, target)), max(0.0, duration))

    def status(self) -> dict[str, Any]:
        """Return transport status for operators and dashboard."""
        return {
            "host": self.host,
            "port": self.port,
            "sent_count": len(self.sent_messages),
            "last_message": self.sent_messages[-1] if self.sent_messages else None,
        }

    def _send_from_message(self, message: UniversalMessage):
        payload = message.payload
        action = payload.get("action", "set")
        if payload.get("cue_number") is not None:
            self.cue(int(payload["cue_number"]), str(payload.get("osc_action", action or "go")))
        elif action == "fade":
            self.fade(int(payload.get("channel", 1)), float(payload.get("value", 0.0)), float(payload.get("duration", 1.0)))
        else:
            self.light(int(payload.get("channel", 1)), float(payload.get("value", payload.get("volume", 0.0))))

    def _build_message(self, address: str, args: list[Any]) -> bytes:
        """Build a valid OSC packet from address and arguments."""
        packet = self._osc_string(address)
        type_tags = "," + "".join(self._tag_for(value) for value in args)
        packet += self._osc_string(type_tags)
        for value in args:
            packet += self._encode_argument(value)
        return packet

    @staticmethod
    def _osc_string(value: str) -> bytes:
        encoded = value.encode("utf-8") + b"\x00"
        padding = (4 - (len(encoded) % 4)) % 4
        return encoded + (b"\x00" * padding)

    @staticmethod
    def _tag_for(value: Any) -> str:
        if isinstance(value, bool):
            return "i"
        if isinstance(value, int):
            return "i"
        if isinstance(value, float):
            return "f"
        return "s"

    @staticmethod
    def _encode_argument(value: Any) -> bytes:
        if isinstance(value, bool):
            return struct.pack(">i", int(value))
        if isinstance(value, int):
            return struct.pack(">i", value)
        if isinstance(value, float):
            return struct.pack(">f", value)
        return OSCAdapter._osc_string(str(value))
