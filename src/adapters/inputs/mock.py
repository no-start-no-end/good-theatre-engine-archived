"""Mock input adapters for rehearsal and testing."""
from __future__ import annotations

import random
import time

from .base import BaseInputAdapter
from ...core.message import UniversalMessage, human_input, sensor_event


class MockMotionSensor(BaseInputAdapter):
    """Simulates a motion sensor. Generates random motion events."""

    def __init__(self, zone: str = "stage", interval: float = 2.0, motion_probability: float = 0.3):
        self.zone = zone
        self.interval = interval
        self.motion_probability = motion_probability
        self._running = False
        self._last_read = 0.0

    def start(self):
        self._running = True

    def stop(self):
        self._running = False

    def read(self) -> UniversalMessage | None:
        if not self._running or (time.time() - self._last_read) < self.interval:
            return None
        self._last_read = time.time()
        detected = random.random() < self.motion_probability
        if not detected:
            return None
        return sensor_event("mock.motion", {"zone": self.zone, "motion": True, "movement_level": round(random.random(), 2)})


class MockCamera(BaseInputAdapter):
    """Simulates camera input. Returns simple scene analysis."""

    def __init__(self, zone: str = "audience", interval: float = 3.0):
        self.zone = zone
        self.interval = interval
        self._running = False
        self._last_read = 0.0

    def start(self):
        self._running = True

    def stop(self):
        self._running = False

    def read(self) -> UniversalMessage | None:
        if not self._running or (time.time() - self._last_read) < self.interval:
            return None
        self._last_read = time.time()
        payload = {
            "people_count": random.randint(0, 30),
            "movement_level": round(random.random(), 2),
            "zone": self.zone,
        }
        return sensor_event("mock.camera", payload, confidence=0.85, tags=["vision"])


class MockMicrophone(BaseInputAdapter):
    """Simulates voice/STT input. Returns fixed or random text commands."""

    def __init__(self, commands: list[str] | None = None, trigger_interval: float = 5.0):
        self.commands = commands or ["raise the tension", "soften the lights", "hold this moment"]
        self.trigger_interval = trigger_interval
        self._running = False
        self._last_read = 0.0

    def start(self):
        self._running = True

    def stop(self):
        self._running = False

    def read(self) -> UniversalMessage | None:
        if not self._running or (time.time() - self._last_read) < self.trigger_interval:
            return None
        self._last_read = time.time()
        return human_input("mock.microphone", {"text": random.choice(self.commands), "channel": "voice"})
