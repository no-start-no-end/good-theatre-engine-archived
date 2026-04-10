"""Structured error log for theatre runs."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Any


@dataclass
class ErrorEntry:
    timestamp: float
    phase: str
    source: str
    message: str
    severity: str = "error"  # error | warning | critical
    recoverable: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "phase": self.phase,
            "source": self.source,
            "message": self.message,
            "severity": self.severity,
            "recoverable": self.recoverable,
            "details": self.details,
        }


class ErrorLog:
    """Persistent structured log of errors and anomalies during a performance run.

    Every error is tagged with phase, severity, and whether it was recoverable.
    Written to JSONL for easy replay analysis.
    """

    def __init__(self, log_dir: str | Path):
        self.path = Path(log_dir) / "error_log.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        message: str,
        phase: str,
        source: str,
        severity: str = "error",
        recoverable: bool = True,
        details: dict[str, Any] | None = None,
    ):
        entry = ErrorEntry(
            timestamp=datetime.now().timestamp(),
            phase=phase,
            source=source,
            message=message,
            severity=severity,
            recoverable=recoverable,
            details=details or {},
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.to_dict()) + "\n")

    def error(self, message: str, phase: str, source: str, **kwargs):
        self.log(message, phase, source, severity="error", **kwargs)

    def warning(self, message: str, phase: str, source: str, **kwargs):
        self.log(message, phase, source, severity="warning", **kwargs)

    def critical(self, message: str, phase: str, source: str, **kwargs):
        self.log(message, phase, source, severity="critical", recoverable=False, **kwargs)

    def read_all(self) -> list[ErrorEntry]:
        if not self.path.exists():
            return []
        entries = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    data = json.loads(line)
                    entries.append(ErrorEntry(**data))
        return entries

    def summary(self) -> dict[str, Any]:
        entries = self.read_all()
        if not entries:
            return {"total": 0, "by_severity": {}, "by_source": {}, "recoverable_count": 0}
        return {
            "total": len(entries),
            "by_severity": {k: sum(1 for e in entries if e.severity == k) for k in ["error", "warning", "critical"]},
            "by_source": {k: sum(1 for e in entries if e.source == k) for k in set(e.source for e in entries)},
            "recoverable_count": sum(1 for e in entries if e.recoverable),
            "non_recoverable": [e.to_dict() for e in entries if not e.recoverable],
        }
