"""Cue list system for structured theatre runs."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class CueType(Enum):
    GO = "go"           # Fire immediately
    WAIT = "wait"       # Wait for trigger
    TIMED = "timed"     # Fire after offset
    FOLLOW = "follow"   # Fire after previous cue completes


@dataclass
class Cue:
    number: int
    description: str
    cue_type: CueType = CueType.GO
    targets: dict[str, Any] = field(default_factory=dict)
    offset_seconds: float = 0.0
    pre_wait: float = 0.0
    tags: list[str] = field(default_factory=list)
    fade_duration: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "description": self.description,
            "cue_type": self.cue_type.value,
            "targets": self.targets,
            "offset_seconds": self.offset_seconds,
            "pre_wait": self.pre_wait,
            "tags": self.tags,
            "fade_duration": self.fade_duration,
        }


class CueList:
    """A numbered cue list for a performance."""

    def __init__(self, name: str = "Untitled Cue List"):
        self.name = name
        self._cues: list[Cue] = []
        self._fired: set[int] = set()
        self._created_at = datetime.now().timestamp()

    def add(self, cue: Cue):
        self._cues.append(cue)

    def add_go(self, number: int, description: str, targets: dict[str, Any], tags: list[str] | None = None):
        self.add(Cue(number=number, description=description, targets=targets, tags=tags or []))

    def get(self, number: int) -> Cue | None:
        for cue in self._cues:
            if cue.number == number:
                return cue
        return None

    def next_after(self, number: int) -> Cue | None:
        candidates = [c for c in self._cues if c.number > number]
        return min(candidates, key=lambda c: c.number) if candidates else None

    def fire(self, number: int) -> Cue | None:
        cue = self.get(number)
        if cue:
            self._fired.add(number)
        return cue

    def is_fired(self, number: int) -> bool:
        return number in self._fired

    def reset(self):
        self._fired.clear()

    def all(self) -> list[Cue]:
        return sorted(self._cues, key=lambda c: c.number)

    def pending(self) -> list[Cue]:
        return [c for c in self.all() if c.number not in self._fired]

    def timeline_seconds(self) -> float:
        if not self._cues:
            return 0.0
        return max(c.offset_seconds + c.pre_wait + c.fade_duration for c in self._cues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "cue_count": len(self._cues),
            "fired_count": len(self._fired),
            "timeline_seconds": self.timeline_seconds(),
            "cues": [c.to_dict() for c in self.all()],
        }
