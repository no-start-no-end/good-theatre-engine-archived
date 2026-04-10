"""Tests for DimensionDriver."""
from __future__ import annotations

from dataclasses import dataclass
import pytest
from src.dimension_driver import DimensionDriver, MappingRule, DimensionState
from src.performance_matrix import PhaseSpace


@dataclass
class FakeMessage:
    tags: list[str]
    payload: dict


class TestMappingRule:
    def test_apply_with_scale(self):
        r = MappingRule("src", "key", "energy", scale=0.5, offset=0.0)
        assert r.apply(1.0) == 0.5
        assert r.apply(0.0) == 0.0

    def test_apply_with_offset(self):
        r = MappingRule("src", "key", "energy", scale=1.0, offset=0.1)
        assert r.apply(0.5) == 0.6

    def test_apply_clamps_to_0_1(self):
        r = MappingRule("src", "key", "energy", scale=1.0, offset=0.0)
        assert r.apply(1.5) == 1.0
        assert r.apply(-0.5) == 0.0


class TestDimensionDriver:
    def test_map_registers_rule(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.0, min=0.0, max=1.0)
        driver = DimensionDriver(space)
        rule = driver.map("audio.amplitude", "level", to_dimension="energy", scale=0.8)
        assert len(driver.rules) == 1
        assert rule.dimension == "energy"
        assert rule.scale == 0.8

    def test_push_updates_dimension(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.0, min=0.0, max=1.0)
        driver = DimensionDriver(space)
        driver.map("audio.amplitude", "level", to_dimension="energy", scale=1.0)
        driver.push("audio.amplitude", "level", 0.7)
        assert space.get("energy") == 0.7

    def test_push_unknown_source_key_ignored(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.0, min=0.0, max=1.0)
        driver = DimensionDriver(space)
        driver.map("audio.amplitude", "level", to_dimension="energy")
        driver.push("audio.amplitude", "wrong_key", 0.7)
        assert space.get("energy") == 0.0

    def test_on_bus_event_routes_to_matching_rule(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.0, min=0.0, max=1.0)
        driver = DimensionDriver(space)
        driver.map("zigbee.front_pir", "occupancy", to_dimension="energy", scale=1.0)
        msg = FakeMessage(tags=["zigbee.front_pir"], payload={"occupancy": 0.9})
        driver.on_bus_event(msg)
        assert space.get("energy") == 0.9

    def test_on_bus_event_ignores_unknown_tag(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.0, min=0.0, max=1.0)
        driver = DimensionDriver(space)
        driver.map("zigbee.front_pir", "occupancy", to_dimension="energy")
        msg = FakeMessage(tags=["zigbee.back_pir"], payload={"occupancy": 0.9})
        driver.on_bus_event(msg)
        assert space.get("energy") == 0.0

    def test_smoothing_ema(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.0, min=0.0, max=1.0)
        driver = DimensionDriver(space)
        driver.map("audio.amplitude", "level", to_dimension="energy", scale=1.0, smoothing=0.5)
        driver.push("audio.amplitude", "level", 1.0)  # first: 0 + 0.5*(1-0) = 0.5
        assert space.get("energy") == 0.5
        driver.push("audio.amplitude", "level", 1.0)  # second: 0.5 + 0.5*(1-0.5) = 0.75
        assert space.get("energy") == 0.75
        driver.push("audio.amplitude", "level", 0.0)  # third: 0.75 + 0.5*(0-0.75) = 0.375
        assert space.get("energy") == 0.375

    def test_disable_rule(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.0, min=0.0, max=1.0)
        driver = DimensionDriver(space)
        driver.map("audio.amplitude", "level", to_dimension="energy")
        driver.disable("audio.amplitude")
        driver.push("audio.amplitude", "level", 0.9)
        assert space.get("energy") == 0.0

    def test_enable_rule(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.0, min=0.0, max=1.0)
        driver = DimensionDriver(space)
        driver.map("audio.amplitude", "level", to_dimension="energy")
        driver.disable("audio.amplitude")
        driver.enable("audio.amplitude")
        driver.push("audio.amplitude", "level", 0.9)
        assert space.get("energy") == 0.9

    def test_unmap_removes_all_rules(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.0, min=0.0, max=1.0)
        space.add_dimension("tension", current=0.0, min=0.0, max=1.0)
        driver = DimensionDriver(space)
        driver.map("audio.amplitude", "level", to_dimension="energy")
        driver.map("audio.amplitude", "peak", to_dimension="tension")
        driver.unmap("audio.amplitude")
        assert len(driver.rules) == 0

    def test_status(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.0, min=0.0, max=1.0)
        driver = DimensionDriver(space)
        driver.map("audio.amplitude", "level", to_dimension="energy")
        driver.push("audio.amplitude", "level", 0.6)
        status = driver.status()
        assert status["total_rules"] == 1
        assert status["smoothed"]["audio.amplitude"] == 0.6
        assert status["dimension_snapshot"]["energy"] == 0.6

    def test_multiple_rules_same_source(self):
        space = PhaseSpace()
        space.add_dimension("energy", current=0.0, min=0.0, max=1.0)
        space.add_dimension("tension", current=0.0, min=0.0, max=1.0)
        driver = DimensionDriver(space)
        driver.map("audio.amplitude", "level", to_dimension="energy", scale=0.5)
        driver.map("audio.amplitude", "peak", to_dimension="tension", scale=1.0)
        driver.push("audio.amplitude", "level", 0.8)   # energy: 0.4
        driver.push("audio.amplitude", "peak", 0.9)  # tension: 0.9
        assert space.get("energy") == 0.4
        assert space.get("tension") == 0.9
