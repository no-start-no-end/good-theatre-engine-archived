"""Health supervisor — monitors the engine's vital signs and can auto-restart components.

The supervisor runs as a background thread, periodically checking:
- All adapter health (MQTT connections, hardware heartbeats)
- Message bus throughput (stall detection)
- Error log critical count
- System resource usage (optional)

If a component fails, the supervisor:
1. Logs the failure with timestamp and context
2. Attempts to restart the component
3. Escalates to the error_log if unrecoverable
4. Notifies via the dashboard SSE feed if available

Design principle: the supervisor observes and repairs, never blocks the main run loop.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from src.core.error_log import ErrorLog


@dataclass
class ComponentHealth:
    """Snapshot of a monitored component's health."""

    name: str
    healthy: bool
    last_check: float
    consecutive_failures: int = 0
    last_error: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SupervisorConfig:
    """Configuration for the health supervisor."""

    check_interval: float = 5.0  # seconds between health checks
    stall_threshold: float = 30.0  # seconds without events before stall warning
    max_consecutive_failures: int = 3  # restart after this many failures
    error_log: ErrorLog | None = None


class HealthSupervisor:
    """Background health monitor and repair agent.

    Usage:
        supervisor = HealthSupervisor(config)
        supervisor.register_adapter("zigbee", zigbee_adapter)
        supervisor.register_adapter("qlab", qlab_watcher)
        supervisor.start()

        # Check status at any time:
        health = supervisor.status()
        if health["system_healthy"]:
            print("All good")
    """

    def __init__(self, config: SupervisorConfig | None = None):
        self.config = config or SupervisorConfig()
        self._components: dict[str, Callable[[], ComponentHealth]] = {}
        self._health: dict[str, ComponentHealth] = {}
        self._running: bool = False
        self._thread: threading.Thread | None = None
        self._lock: threading.Lock = threading.Lock()
        self._last_event_time: float = time.time()
        self._last_event_count: int = 0
        self._event_stalled: bool = False
        self._on_alert: Callable[[str, str, dict], None] | None = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        checker: Callable[[], ComponentHealth],
    ):
        """Register a component with its health checker function.

        The checker is called every check_interval seconds and must return
        a ComponentHealth snapshot.

        Example:
            def check_zigbee():
                zb = zigbee_adapter
                return ComponentHealth(
                    name="zigbee",
                    healthy=zb.is_online(),
                    last_check=time.time(),
                    extra={"devices": len(zb.devices())}
                )
            supervisor.register("zigbee", check_zigbee)
        """
        self._components[name] = checker

    def on_alert(self, callback: Callable[[str, str, dict], None]):
        """Register a callback for health alerts (severity, message, extra)."""
        self._on_alert = callback

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Start the background supervisor thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the supervisor."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        self._thread = None

    def _run(self):
        while self._running:
            self._check_all()
            time.sleep(self.config.check_interval)

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------

    def _check_all(self):
        """Run all health checks and handle failures."""
        for name, checker in list(self._components.items()):
            try:
                health = checker()
            except Exception as exc:  # noqa: BLE001
                health = ComponentHealth(
                    name=name,
                    healthy=False,
                    last_check=time.time(),
                    consecutive_failures=1,
                    last_error=f"{type(exc).__name__}: {exc}",
                )

            with self._lock:
                prev = self._health.get(name)
                was_healthy = prev.healthy if prev else True
                self._health[name] = health

                if not health.healthy:
                    health.consecutive_failures = (
                        (prev.consecutive_failures if prev else 0) + 1
                    )
                    if health.consecutive_failures >= self.config.max_consecutive_failures:
                        if was_healthy:
                            self._alert(
                                "critical",
                                f"Component '{name}' has failed "
                                f"{health.consecutive_failures} times: {health.last_error}",
                                health.extra,
                            )
                        elif health.consecutive_failures == self.config.max_consecutive_failures:
                            self._escalate(name, health)
                else:
                    # Recovered
                    if prev and not prev.healthy and prev.consecutive_failures > 0:
                        self._alert(
                            "info",
                            f"Component '{name}' recovered",
                            health.extra,
                        )

    def _escalate(self, name: str, health: ComponentHealth):
        """Escalate a component failure to the error log."""
        if self.config.error_log:
            self.config.error_log.error(
                message=f"Component '{name}' failed after "
                f"{self.config.max_consecutive_failures} attempts: {health.last_error}",
                phase="supervisor",
                source=f"supervisor.{name}",
                consecutive_failures=health.consecutive_failures,
                recoverable=True,
            )

    def _alert(self, severity: str, message: str, extra: dict):
        import sys as _sys; _sys.stderr.write(f"ALERT id={id(self)} on_alert={id(getattr(self, '_on_alert', None))}\n"); _sys.stderr.flush()
        if self._on_alert:
            self._on_alert(severity, message, extra)
        if severity == "critical" and self.config.error_log:
            self.config.error_log.log(
                message,
                phase="supervisor",
                source="supervisor",
                severity=severity,
            )

    # ------------------------------------------------------------------
    # Event throughput monitoring
    # ------------------------------------------------------------------

    def record_event(self):
        """Call this from the main loop when an event is processed."""
        self._last_event_time = time.time()
        self._last_event_count += 1

    def _check_throughput(self) -> tuple[bool, float]:
        """Returns (is_stalled, seconds_since_last_event)."""
        elapsed = time.time() - self._last_event_time
        is_stalled = elapsed > self.config.stall_threshold
        if is_stalled and not self._event_stalled:
            self._alert(
                "warning",
                f"Event bus stalled — no events for {elapsed:.0f}s",
                {"stall_duration_s": elapsed},
            )
        self._event_stalled = is_stalled
        return is_stalled, elapsed

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return current health status for all monitored components."""
        with self._lock:
            component_status = {
                name: {
                    "healthy": h.healthy,
                    "last_check": h.last_check,
                    "failures": h.consecutive_failures,
                    "last_error": h.last_error,
                    "extra": h.extra,
                }
                for name, h in self._health.items()
            }

        stalled, since_last = self._check_throughput()

        healthy_count = sum(
            1 for h in self._health.values() if h.healthy
        )
        system_healthy = (
            healthy_count == len(self._health)
            and not stalled
            and len(self._health) > 0
        )

        return {
            "system_healthy": system_healthy,
            "monitored": len(self._health),
            "healthy_count": healthy_count,
            "stalled": stalled,
            "seconds_since_last_event": round(since_last, 1),
            "components": component_status,
            "supervisor_running": self._running,
        }

    def component(self, name: str) -> ComponentHealth | None:
        """Return health for a specific component."""
        with self._lock:
            return self._health.get(name)

    def reset(self, name: str):
        """Reset failure counter for a component after manual intervention."""
        with self._lock:
            if name in self._health:
                self._health[name].consecutive_failures = 0
                self._health[name].last_error = ""
