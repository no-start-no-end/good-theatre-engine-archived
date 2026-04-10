"""Tests for the error log and replay tools."""
from __future__ import annotations

import pytest
from src.core.error_log import ErrorLog, ErrorEntry


class TestErrorLog:
    def test_log_and_read(self, tmp_path):
        errlog = ErrorLog(tmp_path)
        errlog.error("Adapter timeout", phase="stabilizing", source="mock.motion")
        errlog.warning("Low confidence", phase="detecting", source="mock.camera")
        errlog.critical("Emergency stop triggered", phase="escalating", source="keyboard")

        entries = errlog.read_all()
        assert len(entries) == 3
        assert entries[0].severity == "error"
        assert entries[2].severity == "critical"
        assert not entries[2].recoverable

    def test_summary(self, tmp_path):
        errlog = ErrorLog(tmp_path)
        errlog.error("a", phase="detecting", source="x")
        errlog.error("b", phase="detecting", source="y")
        errlog.warning("c", phase="stabilizing", source="x")

        summary = errlog.summary()
        assert summary["total"] == 3
        assert summary["by_severity"]["error"] == 2
        assert summary["by_severity"]["warning"] == 1
        assert summary["by_source"]["x"] == 2

    def test_to_dict(self, tmp_path):
        errlog = ErrorLog(tmp_path)
        errlog.log("test", phase="detecting", source="test", details={"key": "value"})
        entries = errlog.read_all()
        assert entries[0].to_dict()["details"]["key"] == "value"
