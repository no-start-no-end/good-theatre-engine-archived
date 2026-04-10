"""Cue runner that drives a CueList through a PerformanceRunner.

Error handling strategy:
- Each target send is wrapped in try/except
- Failed sends are retried up to `max_retries` times with backoff
- Permanently failed targets go to a dead-letter queue (DLQ)
- All errors are logged to ErrorLog for the performance record
- The cue list continues even if individual targets fail (graceful degradation)
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..cues import Cue, CueList, CueType
from ..core.error_log import ErrorLog
from ..core.interface import InterfaceLayer
from ..core.message import output_command
from ..performance import Phase, PerformanceRunner


@dataclass
class DeadLetterItem:
    """A command that failed after all retries — for manual replay or analysis."""

    cue: Cue
    target_name: str
    params: dict[str, Any]
    attempts: int
    last_error: str
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))


class CueFireError(Exception):
    """Raised when a cue target fails after all retries."""


@dataclass
class CueRunner:
    """Run a numbered cue list through the engine.

    Fires cues as timed events, converting each cue's targets into
    UniversalMessage output commands routed through the interface.
    Supports error recovery: failed targets are retried with exponential
    backoff, then sent to a dead-letter queue if they remain unsuccessful.
    """

    cue_list: CueList
    interface: InterfaceLayer
    performance_runner: PerformanceRunner | None = None
    on_cue_fire: Callable[[Cue], None] | None = None
    max_retries: int = 2
    error_log: ErrorLog | None = None
    _running: bool = False
    _thread: threading.Thread | None = None
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _dlq: list[DeadLetterItem] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self):
        """Begin cue playback in a background thread."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._dlq.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Halt cue playback."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        self.cue_list.reset()

    def _run(self):
        """Process cues in time order."""
        start_time = time.time()
        pending = {c.number: c for c in self.cue_list.all()}
        fired_numbers: set[int] = set()
        next_cue_number = min(pending.keys()) if pending else None

        while self._running and pending and not self._stop_event.is_set():
            elapsed = time.time() - start_time

            for number, cue in list(pending.items()):
                if number in fired_numbers:
                    continue
                if cue.offset_seconds <= elapsed:
                    self._fire_cue(cue)
                    fired_numbers.add(number)
                    del pending[number]

                    remaining = sorted(pending.keys())
                    next_cue_number = remaining[0] if remaining else None

            self._stop_event.wait(0.05)

        self._running = False

    def _fire_cue(self, cue: Cue):
        """Fire a single cue: apply targets with retry logic and DLQ on failure."""
        if self.on_cue_fire:
            self.on_cue_fire(cue)

        for target_name, params in cue.targets.items():
            self._send_target_with_retry(cue, target_name, params)

        self.cue_list.fire(cue.number)

    def _send_target_with_retry(
        self, cue: Cue, target_name: str, params: dict[str, Any]
    ):
        """Send a target command with retry + exponential backoff."""
        last_error = ""
        for attempt in range(self.max_retries + 1):
            try:
                msg = output_command(
                    target_name,
                    params,
                    source=f"cue.{cue.number}",
                )
                self.interface.receive(msg)
                return  # Success
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.max_retries:
                    # Exponential backoff: 50ms, 100ms, 200ms...
                    sleep_time = 0.05 * (2**attempt)
                    time.sleep(sleep_time)

        # Permanently failed after all retries
        dlq_item = DeadLetterItem(
            cue=cue,
            target_name=target_name,
            params=params,
            attempts=self.max_retries + 1,
            last_error=last_error,
        )
        with self._lock:
            self._dlq.append(dlq_item)

        phase = self.performance_runner.config.phase.value if self.performance_runner else "unknown"
        if self.error_log:
            self.error_log.error(
                message=f"Cue {cue.number} target '{target_name}' failed after "
                f"{self.max_retries + 1} attempts: {last_error}",
                phase=phase,
                source=f"cue_runner.{target_name}",
                cue_number=cue.number,
                target=target_name,
                attempts=self.max_retries + 1,
                recoverable=True,
            )

    def jump_to(self, number: int):
        """Fire a specific cue immediately and skip ahead."""
        cue = self.cue_list.get(number)
        if cue:
            self._fire_cue(cue)
            self.cue_list.fire(number)

    def replay_dlq_item(self, index: int) -> bool:
        """Replay a specific DLQ item. Returns True if successful."""
        with self._lock:
            if index < 0 or index >= len(self._dlq):
                return False
            item = self._dlq[index]

        try:
            msg = output_command(
                item.target_name,
                item.params,
                source=f"cue.{item.cue.number} (dlq replay)",
            )
            self.interface.receive(msg)
            with self._lock:
                self._dlq.pop(index)
            return True
        except Exception:  # noqa: BLE001
            return False

    def dlq_status(self) -> dict[str, Any]:
        """Return DLQ summary."""
        with self._lock:
            return {
                "count": len(self._dlq),
                "items": [
                    {
                        "cue": item.cue.number,
                        "target": item.target_name,
                        "attempts": item.attempts,
                        "error": item.last_error,
                        "timestamp": item.timestamp,
                    }
                    for item in self._dlq
                ],
            }

    def status(self) -> dict[str, Any]:
        """Return current cue runner status."""
        return {
            "running": self._running,
            "cue_list": self.cue_list.name,
            "total_cues": len(self.cue_list.all()),
            "fired": len(self.cue_list._fired),
            "pending": [c.number for c in self.cue_list.pending()],
            "dlq_count": len(self._dlq),
        }
