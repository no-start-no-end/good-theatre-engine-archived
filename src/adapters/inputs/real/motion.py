"""Motion sensor adapter reading from UDP broadcast (e.g., PIR sensor on IoT device)."""
from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any

from . import BaseInputAdapter
from ....core.message import UniversalMessage, sensor_event


@dataclass
class MotionSensor(BaseInputAdapter):
    """Listen for motion detection UDP packets from an IoT PIR sensor.

    Expects JSON payload: {"zone": "stage_left", "motion": 1, "confidence": 0.95}
    Replace the host/port with your actual sensor's broadcast address.
    """

    host: str = "0.0.0.0"
    port: int = 5001
    zone: str = "stage"
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
            data, _ = self._sock.recvfrom(1024)
            payload = json.loads(data.decode("utf-8"))
            return sensor_event(
                source=f"motion.{payload.get('zone', self.zone)}",
                payload={
                    "zone": payload.get("zone", self.zone),
                    "motion": bool(payload.get("motion", 0)),
                    "movement_level": float(payload.get("confidence", 0.5)),
                },
                confidence=float(payload.get("confidence", 0.85)),
                tags=["motion", payload.get("zone", self.zone)],
            )
        except (BlockingIOError, json.JSONDecodeError, Exception):
            return None

    def status(self) -> dict[str, Any]:
        return {
            "type": "motion_sensor",
            "host": self.host,
            "port": self.port,
            "zone": self.zone,
            "running": self._running,
        }
