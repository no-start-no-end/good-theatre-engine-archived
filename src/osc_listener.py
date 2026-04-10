"""OSC listener for receiving real-time OSC messages from QLab or touch controllers.

Receives OSC packets on a UDP port, parses them, and converts them to
UniversalMessage objects for injection into the Good Theatre message bus.
"""
from __future__ import annotations

import socket
import struct
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from src.core.message import UniversalMessage, human_input


@dataclass
class OSCListener:
    """Receive OSC messages over UDP and convert them to UniversalMessage objects.

    Configure the address/port to match the OSC sender (QLab uses port 53001 by default
    for outgoing OSC, though this is configurable per workspace).

    Callbacks are invoked for each matching OSC address pattern.
    """

    host: str = "0.0.0.0"
    port: int = 53001
    source_name: str = "osc"
    _sock: Any = None
    _running: bool = False
    _callbacks: dict[str, Callable[[UniversalMessage], None]] = field(default_factory=dict)

    # OSC type tag → Python type
    TAG_MAP = {
        ord("i"): lambda b: struct.unpack(">i", b)[0],
        ord("f"): lambda b: struct.unpack(">f", b)[0],
        ord("s"): lambda b: b.decode("utf-8", errors="ignore").rstrip("\x00"),
        ord("T"): lambda _: True,
        ord("F"): lambda _: False,
        ord("N"): lambda _: None,
    }

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.setblocking(False)
        self._running = True

    def stop(self):
        self._running = False
        if self._sock:
            self._sock.close()
            self._sock = None

    def on(self, address: str, callback: Callable[[UniversalMessage], None]):
        """Register a callback for a specific OSC address (e.g. '/cue/5/go')."""
        self._callbacks[address] = callback

    def read(self) -> Optional[UniversalMessage]:
        """Poll for the next OSC message. Returns None if nothing ready."""
        if not self._running:
            return None
        try:
            data, _ = self._sock.recvfrom(4096)
        except (BlockingIOError, OSError):
            return None

        try:
            address, type_offset, args_offset = self._parse_header(data)
            args = self._parse_args(data, type_offset, args_offset)
            cue_number = self._extract_cue_number(address)

            msg = self._build_message(address, cue_number, args)
            return msg
        except Exception:
            return None

    def _parse_header(self, data: bytes) -> tuple[str, int, int]:
        """Extract OSC address and offsets from packet."""
        end = 0
        while end < len(data) and data[end] != 0:
            end += 1
        address = data[:end].decode("utf-8", errors="ignore")

        # Skip address, find type tag string (aligned to 4-byte boundary)
        offset = end + 1
        offset += (4 - (offset % 4)) % 4
        type_offset = offset

        # Find end of type tag string
        tag_end = offset
        while tag_end < len(data) and data[tag_end] != 0:
            tag_end += 1
        args_offset = tag_end + 1
        args_offset += (4 - (args_offset % 4)) % 4

        return address, type_offset, args_offset

    def _parse_args(self, data: bytes, type_offset: int, args_offset: int) -> list:
        """Parse typed arguments from OSC packet."""
        if type_offset >= len(data) or data[type_offset] != 44:  # ','
            return []
        args = []
        i = type_offset + 1  # skip ','
        j = args_offset
        while i < len(data) and data[i] != 0:
            tag = data[i]
            i += 1
            if tag == ord("s"):
                # Strings are null-terminated and padded to 4-byte boundary
                end = j
                while end < len(data) and data[end] != 0:
                    end += 1
                result = data[j:end].decode("utf-8", errors="ignore")
                args.append(result)
                # Advance j to next 4-byte boundary
                j = end + 1
                j += (4 - (j % 4)) % 4
            elif tag in self.TAG_MAP and j + 4 <= len(data):
                args.append(self.TAG_MAP[tag](data[j : j + 4]))
                j += 4
            elif tag not in self.TAG_MAP:
                break
        return args

    def _extract_cue_number(self, address: str) -> Optional[int]:
        parts = address.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "cue":
            try:
                return int(parts[1])
            except ValueError:
                return None
        return None

    def _build_message(
        self, address: str, cue_number: Optional[int], args: list
    ) -> UniversalMessage:
        """Convert a parsed OSC message to a UniversalMessage."""
        tags = ["osc", address.strip("/").replace("/", "_")]

        if cue_number is not None:
            if address.endswith("/go"):
                action = "fire"
            elif address.endswith("/stop"):
                action = "stop"
            elif address.endswith("/pause"):
                action = "pause"
            elif address.endswith("/load"):
                action = "load"
            else:
                action = address.strip("/").split("/")[-1]

            payload = {
                "osc_action": action,
                "cue_number": cue_number,
                "raw_address": address,
                "args": args,
            }
            tags.append(f"cue_{cue_number}")
            tags.append(f"qlab_{action}")
        else:
            payload = {"raw_address": address, "args": args}
            tags.append("raw_osc")

        return human_input(
            f"osc.{cue_number or address.strip('/').replace('/', '_')}",
            payload,
            tags=tags,
        )

    def status(self) -> dict[str, Any]:
        return {
            "type": "osc_listener",
            "host": self.host,
            "port": self.port,
            "running": self._running,
            "callbacks": list(self._callbacks.keys()),
        }
