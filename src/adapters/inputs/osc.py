"""OSC input adapter — receive real-time OSC messages from QLab, touch controllers, etc."""
from __future__ import annotations

import socket
import struct
from dataclasses import dataclass
from typing import Any

from .base import BaseInputAdapter
from ...core.message import UniversalMessage, human_input


# OSC address patterns and their interpretation
OSC_PATTERNS = {
    "/cue/{n}/go": "cue_fire",
    "/cue/{n}/stop": "cue_stop",
    "/cue/{n}/load": "cue_load",
    "/dict/key": "dict_key",
    "/midi/note": "midi_note",
    "/midi/cc": "midi_cc",
    "/sys/heartbeat": "heartbeat",
}


@dataclass
class OSCInput(BaseInputAdapter):
    """Receive OSC messages over UDP and convert them to UniversalMessage objects.

    Supports common OSC patterns used by QLab, TouchDesigner, and custom
    OSC senders. Configure the address/port to match your sender.
    """

    host: str = "0.0.0.0"
    port: int = 53001       # QLab OSC default; adjust as needed
    source_name: str = "osc"
    _sock: Any = None
    _running: bool = False

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

    def read(self) -> UniversalMessage | None:
        if not self._running:
            return None
        try:
            data, _ = self._sock.recvfrom(4096)
            return self._parse_osc(data)
        except (BlockingIOError, OSError):
            return None

    def _parse_osc(self, data: bytes) -> UniversalMessage | None:
        """Parse a raw OSC packet into a UniversalMessage."""
        try:
            address = self._read_string(data, 0)
            if address is None:
                return None

            # Detect the pattern
            cue_number = self._extract_cue_number(address)
            pattern = self._classify(address, cue_number)

            # Read type tag string if present (after null-padded address)
            type_offset = len(address) + 1 + (4 - (len(address) % 4)) % 4
            if type_offset < len(data) and data[type_offset: type_offset + 2] == b",,":
                # OSC with type tags — extract arguments
                args = self._read_typed_args(data, type_offset)
            else:
                args = []

            return self._build_message(address, pattern, cue_number, args)

        except Exception:
            return None

    def _read_string(self, data: bytes, offset: int) -> str | None:
        """Read a null-terminated string from OSC data."""
        end = offset
        while end < len(data) and data[end] != 0:
            end += 1
        if end >= len(data):
            return None
        return data[offset:end].decode("utf-8", errors="ignore")

    def _read_typed_args(self, data: bytes, type_offset: int) -> list:
        """Read typed arguments from OSC packet after type tag."""
        args = []
        i = type_offset + 2  # skip ",," or ",{types}"
        while i < len(data):
            tag = data[i]
            i += 1
            if tag == 105:  # 'i' — int32
                args.append(struct.unpack(">i", data[i : i + 4])[0])
                i += 4
            elif tag == 102:  # 'f' — float32
                args.append(struct.unpack(">f", data[i : i + 4])[0])
                i += 4
            elif tag == 115:  # 's' — string
                s = self._read_string(data, i)
                args.append(s)
                i += len(s) + 1 + (4 - ((len(s) + 1) % 4)) % 4
            elif tag == 105 and i + 4 <= len(data):  # another int
                args.append(struct.unpack(">i", data[i : i + 4])[0])
                i += 4
            else:
                break
        return args

    def _extract_cue_number(self, address: str) -> int | None:
        """Extract cue number from an OSC address like /cue/5/go."""
        parts = address.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "cue":
            try:
                return int(parts[1])
            except ValueError:
                return None
        return None

    def _classify(self, address: str, cue_number: int | None) -> str:
        """Classify OSC address into an action pattern."""
        if cue_number is not None:
            if address.endswith("/go"):
                return "cue_fire"
            if address.endswith("/stop"):
                return "cue_stop"
            if address.endswith("/load"):
                return "cue_load"
            if address.endswith("/pause"):
                return "cue_pause"
        if "/midi/note" in address:
            return "midi_note"
        if "/midi/cc" in address:
            return "midi_cc"
        if "/sys/heartbeat" in address:
            return "heartbeat"
        return "raw_osc"

    def _build_message(
        self, address: str, pattern: str, cue_number: int | None, args: list
    ) -> UniversalMessage:
        """Build an appropriate UniversalMessage from parsed OSC data."""
        if pattern in ("cue_fire", "cue_stop", "cue_pause", "cue_load"):
            return human_input(
                f"osc.cue_{cue_number}",
                {
                    "osc_action": pattern.replace("cue_", ""),
                    "cue_number": cue_number,
                    "raw_address": address,
                    "args": args,
                },
                tags=["osc", f"cue_{cue_number}", pattern],
            )
        elif pattern == "midi_note":
            return human_input(
                "osc.midi",
                {
                    "action": "note",
                    "note": args[0] if len(args) > 0 else 0,
                    "velocity": args[1] if len(args) > 1 else 0,
                    "raw_address": address,
                },
                tags=["osc", "midi"],
            )
        elif pattern == "heartbeat":
            return human_input("osc.heartbeat", {"action": "heartbeat"}, tags=["osc", "heartbeat"])
        else:
            return human_input(
                "osc.raw",
                {"raw_address": address, "args": args},
                tags=["osc", "raw"],
            )

    def status(self) -> dict[str, Any]:
        return {
            "type": "osc_input",
            "host": self.host,
            "port": self.port,
            "running": self._running,
        }
