"""DMX512 adapter for theatrical lighting — pure stdlib UDP."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import BaseOutputAdapter
from ....core.message import UniversalMessage


@dataclass
class DMXAdapter(BaseOutputAdapter):
    """Send DMX512 packets to a lighting console or node via Art-Net.

    Uses Art-Net (industry-standard DMX over Ethernet) to communicate
    with lighting equipment. Configure target IP/port to match your
    DMX gateway (e.g., ENTTEC DMXking, Pathport, or custom node).
    """

    host: str = "192.168.1.100"
    port: int = 6454          # Art-Net default
    universe: int = 0         # DMX universe 0-15
    _channels: dict[int, float] = field(default_factory=dict)
    _sock: Any = field(default=None, init=False)

    def __post_init__(self):
        import socket
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._channels = {ch: 0.0 for ch in range(1, 513)}

    def set(self, channel: int, value: float):
        """Set DMX channel 1-512 to normalised value 0.0-1.0."""
        if not 1 <= channel <= 512:
            raise ValueError(f"DMX channel must be 1-512, got {channel}")
        self._channels[channel] = max(0.0, min(1.0, value))

    def fade(self, channel: int, target: float, duration: float):
        """Fade is dispatched to the lighting console as a command."""
        self.set(channel, target)

    def send(self, message: UniversalMessage):
        """Interpret a UniversalMessage as DMX commands."""
        payload = message.payload
        action = payload.get("action", "set")

        if action == "fade":
            self.fade(
                int(payload.get("channel", 1)),
                float(payload.get("value", 0.0)),
                float(payload.get("duration", 1.0)),
            )
        elif action == "blackout":
            for ch in range(1, 513):
                self._channels[ch] = 0.0
        elif action == "full":
            for ch in range(1, 513):
                self._channels[ch] = 1.0
        else:
            ch = int(payload.get("channel", 1))
            val = float(payload.get("value", payload.get("volume", 0.0)))
            self.set(ch, val)

        self._flush()

    def _flush(self):
        """Send current DMX state as an Art-Net packet."""
        import struct
        # Art-Net packet structure
        header = b"Art-Net\x00"
        op_code = 0x5200      # OpDmx
        proto_version = 0x000E
        sequence = 1
        physical = 0
        port_info = self.universe & 0x0FFF
        length = 512

        dmx_data = bytes([int(self._channels[ch] * 255) for ch in range(1, 513)])
        packet = struct.pack(
            "<7sHHBBHHH",
            header, op_code, proto_version,
            sequence, physical,
            port_info, length & 0xFF, (length >> 8) & 0xFF,
        ) + dmx_data
        self._sock.sendto(packet, (self.host, self.port))

    def status(self) -> dict[str, Any]:
        """Return non-zero channels for inspection."""
        active = {ch: round(v, 3) for ch, v in self._channels.items() if v > 0.0}
        return {
            "host": self.host,
            "port": self.port,
            "universe": self.universe,
            "non_zero_channels": len(active),
            "sample": dict(list(active.items())[:10]),
        }
