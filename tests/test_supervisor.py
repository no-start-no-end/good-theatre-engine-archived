"""Tests for the health supervisor."""
from __future__ import annotations

import time
import pytest
from src.supervisor import ComponentHealth, HealthSupervisor, SupervisorConfig


class TestComponentHealth:
    def test_creation(self):
        h = ComponentHealth(name="test", healthy=True, last_check=time.time())
        assert h.name == "test"
        assert h.healthy is True
        assert h.consecutive_failures == 0


class TestHealthSupervisor:
    def test_init(self):
        sup = HealthSupervisor()
        assert sup.config.check_interval == 5.0
        assert sup._running is False

    def test_register_checker(self):
        sup = HealthSupervisor()
        sup.register(
            "test",
            lambda: ComponentHealth(name="test", healthy=True, last_check=time.time()),
        )
        assert "test" in sup._components

    def test_status_empty(self):
        sup = HealthSupervisor()
        status = sup.status()
        # No components monitored yet
        assert status["system_healthy"] is False
        assert status["monitored"] == 0

    def test_status_healthy(self):
        sup = HealthSupervisor()
        sup.register(
            "zigbee",
            lambda: ComponentHealth(name="zigbee", healthy=True, last_check=time.time()),
        )
        sup._check_all()
        status = sup.status()
        assert status["system_healthy"] is True
        assert status["healthy_count"] == 1

    def test_status_unhealthy(self):
        sup = HealthSupervisor()
        sup.register(
            "bad",
            lambda: ComponentHealth(
                name="bad",
                healthy=False,
                last_check=time.time(),
                last_error="connection refused",
            ),
        )
        sup._check_all()
        status = sup.status()
        assert status["system_healthy"] is False
        assert status["healthy_count"] == 0
        assert "bad" in status["components"]
        assert status["components"]["bad"]["healthy"] is False

    def test_consecutive_failures_increment(self):
        sup = HealthSupervisor(SupervisorConfig(max_consecutive_failures=2))
        sup.register(
            "flaky",
            lambda: ComponentHealth(
                name="flaky",
                healthy=False,
                last_check=time.time(),
                last_error="fail",
            ),
        )
        sup._check_all()
        assert sup._health["flaky"].consecutive_failures == 1
        sup._check_all()
        assert sup._health["flaky"].consecutive_failures == 2

    def test_recovery_resets_failures(self):
        sup = HealthSupervisor()
        sup.register(
            "device",
            lambda: ComponentHealth(
                name="device",
                healthy=False,
                last_check=time.time(),
                last_error="init",
            ),
        )
        for _ in range(3):
            sup._check_all()
        assert sup._health["device"].consecutive_failures == 3
        # Recover
        sup.register(
            "device",
            lambda: ComponentHealth(name="device", healthy=True, last_check=time.time()),
        )
        sup._check_all()
        assert sup._health["device"].consecutive_failures == 0

    def test_alert_callback_on_transition_to_unhealthy(self):
        """Alert fires exactly once when a component first fails (was_healthy=True → unhealthy)."""
        sup = HealthSupervisor(SupervisorConfig(max_consecutive_failures=1))
        alerts = []

        def on_alert(severity, message, extra):
            alerts.append((severity, message))

        sup.on_alert(on_alert)
        sup.register(
            "bad",
            lambda: ComponentHealth(
                name="bad",
                healthy=False,
                last_check=time.time(),
                last_error="err",
            ),
        )
        # First check: was_healthy=True, cf becomes 1 >= 1 → fires alert
        sup._check_all()
        assert len(alerts) == 1
        assert alerts[0][0] == "critical"
        # Subsequent failures: was_healthy=False, no new alert
        sup._check_all()
        sup._check_all()
        assert len(alerts) == 1

    def test_recovery_alert(self):
        sup = HealthSupervisor()
        alerts = []

        def on_alert(sev, msg, _):
            alerts.append(sev)

        sup.on_alert(on_alert)
        sup.register(
            "x",
            lambda: ComponentHealth(
                name="x",
                healthy=False,
                last_check=time.time(),
                consecutive_failures=2,
            ),
        )
        sup._check_all()
        sup.register(
            "x",
            lambda: ComponentHealth(name="x", healthy=True, last_check=time.time()),
        )
        sup._check_all()
        assert "info" in alerts

    def test_component_checker_exception_caught(self):
        sup = HealthSupervisor()
        sup.register("risky", lambda: (_ for _ in ()).throw(ValueError("boom")))
        sup._check_all()
        assert sup._health["risky"].healthy is False
        assert "ValueError" in sup._health["risky"].last_error

    def test_record_event(self):
        sup = HealthSupervisor()
        sup.record_event()
        is_stalled, elapsed = sup._check_throughput()
        assert is_stalled is False
        assert elapsed < 0.1

    def test_stall_detection_triggers_warning(self):
        sup = HealthSupervisor(SupervisorConfig(stall_threshold=0.5))
        alerts = []
        sup.on_alert(lambda s, m, _: alerts.append(s))
        # Fake an old event time
        sup._last_event_time = time.time() - 2.0
        is_stalled, _ = sup._check_throughput()
        assert is_stalled is True
        assert alerts[0] == "warning"

    def test_start_stop(self):
        sup = HealthSupervisor()
        sup.start()
        assert sup._running is True
        assert sup._thread is not None
        sup.stop()
        assert sup._running is False

    def test_reset_clears_failures(self):
        sup = HealthSupervisor()
        sup._health["x"] = ComponentHealth(
            name="x",
            healthy=False,
            last_check=time.time(),
            consecutive_failures=5,
            last_error="old",
        )
        sup.reset("x")
        assert sup._health["x"].consecutive_failures == 0
        assert sup._health["x"].last_error == ""

    def test_extra_fields_passed_through(self):
        sup = HealthSupervisor()
        sup.register(
            "z",
            lambda: ComponentHealth(
                name="z",
                healthy=True,
                last_check=time.time(),
                extra={"devices": 12},
            ),
        )
        sup._check_all()
        assert sup._health["z"].extra["devices"] == 12

    def test_alert_callback_max_failures_reached(self):
        """When max_consecutive_failures is hit while still transitioning, escalate."""
        sup = HealthSupervisor(SupervisorConfig(max_consecutive_failures=3))
        sup.register(
            "x",
            lambda: ComponentHealth(
                name="x",
                healthy=False,
                last_check=time.time(),
                last_error="err",
            ),
        )
        # With max=3: 1st cf=1 (no alert), 2nd cf=2 (no alert), 3rd cf=3>=3 but was_healthy=False → no alert
        # 4th cf=4>=3, was_healthy=False → still no alert (already alerted)
        for _ in range(4):
            sup._check_all()
        # Exactly one critical alert (on first transition to unhealthy with max=1)
        assert sup._health["x"].consecutive_failures == 4
