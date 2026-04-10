"""Knowledge storage for Good Theatre Engine."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Any


DEFAULT_CONSTRAINTS = {
    "max_volume": 0.8,
    "min_lighting_transition": 0.5,
    "max_light_level": 1.0,
}


@dataclass
class PerformanceState:
    name: str = "Good Theatre"
    phase: str = "idle"
    energy_level: float = 0.5
    audience_engagement: float = 0.5
    learned_patterns: list[dict[str, Any]] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=lambda: DEFAULT_CONSTRAINTS.copy())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PerformanceState":
        merged = cls().to_dict()
        merged.update(data)
        return cls(**merged)


class KnowledgeBase:
    """Persistent state and learned patterns.

    Svensk kommentar: kunskapsbasen ska vara enkel att förstå och lätt att
    byta ut. Därför används JSON/JSONL istället för en databas.
    """

    def __init__(self, storage_path: str):
        self.storage_root = Path(storage_path)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.storage_root / "performance_state.json"
        self.patterns_path = self.storage_root / "patterns.jsonl"
        self._state = self._load_or_create_state()

    def _load_or_create_state(self) -> PerformanceState:
        if self.state_path.exists():
            try:
                raw = self.state_path.read_text().strip()
                if raw:
                    return PerformanceState.from_dict(json.loads(raw))
            except (json.JSONDecodeError, OSError, TypeError):
                pass
        state = PerformanceState()
        self.save_state(state)
        return state

    def save_state(self, state: PerformanceState):
        self._state = state
        self.state_path.write_text(json.dumps(state.to_dict(), indent=2))

    def load_state(self) -> PerformanceState:
        self._state = self._load_or_create_state()
        return self._state

    def log_pattern(self, trigger: str, outcome: str, success: float):
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "trigger": trigger,
            "outcome": outcome,
            "success": max(0.0, min(1.0, success)),
        }
        with self.patterns_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        self._state.learned_patterns.append(entry)
        self.save_state(self._state)

    def get_patterns(self, trigger: str) -> list[dict[str, Any]]:
        return [pattern for pattern in self._read_patterns() if pattern.get("trigger") == trigger]

    def _read_patterns(self) -> list[dict[str, Any]]:
        if not self.patterns_path.exists():
            return []
        with self.patterns_path.open("r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def get_context(self) -> dict[str, Any]:
        state = self.load_state()
        patterns = self._read_patterns()
        return {
            "state": state.to_dict(),
            "patterns": patterns,
            "recent_patterns": patterns[-10:],
            "constraints": state.constraints,
        }
