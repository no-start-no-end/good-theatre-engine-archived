"""Mock output adapters with verbose state for observability."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import BaseOutputAdapter
from ...core.message import UniversalMessage


@dataclass
class MockLightAdapter(BaseOutputAdapter):
    channels: dict[int, float] = field(default_factory=dict)

    def set(self, channel: int, value: float):
        self.channels[channel] = max(0.0, min(1.0, value))
        print(f"[light] channel={channel} value={self.channels[channel]:.2f}")

    def fade(self, channel: int, target: float, duration: float):
        self.channels[channel] = max(0.0, min(1.0, target))
        print(f"[light] fade channel={channel} target={self.channels[channel]:.2f} duration={duration:.2f}s")

    def send(self, message: UniversalMessage):
        payload = message.payload
        if payload.get("action") == "fade":
            self.fade(int(payload.get("channel", 1)), float(payload.get("value", 0.0)), float(payload.get("duration", 1.0)))
        else:
            self.set(int(payload.get("channel", 1)), float(payload.get("value", 0.0)))

    def status(self) -> dict[str, Any]:
        return {"channels": self.channels}


@dataclass
class MockAudioAdapter(BaseOutputAdapter):
    volumes: dict[int, float] = field(default_factory=dict)
    last_note: dict[str, int] | None = None

    def set_volume(self, channel: int, volume: float):
        self.volumes[channel] = max(0.0, min(1.0, volume))
        print(f"[audio] channel={channel} volume={self.volumes[channel]:.2f}")

    def play_note(self, channel: int, note: int, velocity: int):
        self.last_note = {"channel": channel, "note": note, "velocity": velocity}
        print(f"[audio] play channel={channel} note={note} velocity={velocity}")

    def send(self, message: UniversalMessage):
        payload = message.payload
        if payload.get("action") == "play_note":
            self.play_note(int(payload.get("channel", 1)), int(payload.get("note", 60)), int(payload.get("velocity", 80)))
        else:
            self.set_volume(int(payload.get("channel", 1)), float(payload.get("volume", payload.get("value", 0.5))))

    def status(self) -> dict[str, Any]:
        return {"volumes": self.volumes, "last_note": self.last_note}


@dataclass
class MockDisplayAdapter(BaseOutputAdapter):
    current_text: str = ""
    style: str = "normal"

    def show(self, text: str, style: str = "normal"):
        self.current_text = text
        self.style = style
        print(f"[display] style={style} text={text}")

    def send(self, message: UniversalMessage):
        self.show(str(message.payload.get("text", "")), str(message.payload.get("style", "normal")))

    def status(self) -> dict[str, Any]:
        return {"current_text": self.current_text, "style": self.style}
