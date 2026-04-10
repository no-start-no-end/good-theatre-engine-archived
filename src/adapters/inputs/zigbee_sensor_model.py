"""Zigbee sensor model for Good Theatre Engine.

This model defines how Zigbee devices map to GTE dimensions and feeling states.

FUTURE: Replace with actual device definitions from Z2M API or config.
Currently a placeholder — swap out when real hardware is available.

================================================================================
SENSOR MODEL
================================================================================

Each Zigbee device property maps to one or more GTE dimensions:

  Device property       →  GTE dimension  →  Feeling state
  ─────────────────────────────────────────────────────────────
  occupancy             →  presence       →  Detecting / Stabilizing
  illumination          →  energy         →  Escalating / Dispersing
  temperature           →  (reserved)     →  (future)
  motion_detected       →  presence       →  Detecting
  click/hold (switch)   →  tension        →  Escalating

Dimension rules:
  presence  ∈ [0.0, 1.0]   — hur mycket som rör sig / är i rummet
  energy    ∈ [0.0, 1.0]   — ljusnivå / ljud-intensitet
  tension   ∈ [0.0, 1.0]   — förändringshastighet (computed from rate-of-change)

Feeling states are computed from dimension vectors:

  Detecting     ← presence > 0.1, first time in this session
  Stabilizing   ← presence high, tension low, stable
  Suspended     ← presence low, tension low
  Escalating    ← tension rising, energy rising
  Dispersing    ← energy falling, tension falling from peak

================================================================================
DEVICE PLACEHOLDERS
================================================================================

These define expected Zigbee devices. Replace with actual Z2M device list.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SensorDefinition:
    """Definition of a single sensor input and how it maps to GTE dimensions."""

    z2m_name: str           # Zigbee2MQTT friendly_name in config
    device_type: str       # "pir", "illuminance", "switch", "temperature"
    properties: list[str]   # Which Z2M properties this device provides
    primary_dimension: str  # "presence" | "energy" | "tension"
    secondary_dimensions: list[str] = field(default_factory=list)
    description: str = ""

    def to_mapping_rule(self) -> dict[str, Any]:
        """Return a DimensionDriver mapping rule for this sensor."""
        return {
            "source_tag": f"zigbee.{self.z2m_name}",
            "dimension": self.primary_dimension,
            "properties": self.properties,
        }


# ------------------------------------------------------------------
# Placeholder device registry
# Replace with actual device names from Z2M configuration
# ------------------------------------------------------------------

DEVICE_REGISTRY: dict[str, SensorDefinition] = {
    # PIR / occupancy sensors
    "front_pir": SensorDefinition(
        z2m_name="front_pir",
        device_type="pir",
        properties=["occupancy", "battery"],
        primary_dimension="presence",
        description="Motion sensor at room entrance",
    ),
    "stage_pir": SensorDefinition(
        z2m_name="stage_pir",
        device_type="pir",
        properties=["occupancy", "battery"],
        primary_dimension="presence",
        secondary_dimensions=["tension"],
        description="Motion sensor on stage",
    ),
    "audience_pir": SensorDefinition(
        z2m_name="audience_pir",
        device_type="pir",
        properties=["occupancy", "battery"],
        primary_dimension="presence",
        description="Motion sensor in audience area",
    ),
    # Illuminance sensors
    "main_light_sensor": SensorDefinition(
        z2m_name="main_light_sensor",
        device_type="illuminance",
        properties=["illuminance_lux"],
        primary_dimension="energy",
        description="Light level sensor — drives energy dimension",
    ),
    # Switches / dimmers
    "stage_dimmer": SensorDefinition(
        z2m_name="stage_dimmer",
        device_type="switch",
        properties=["action", "brightness"],
        primary_dimension="tension",
        secondary_dimensions=["energy"],
        description="Dimmer switch — action events drive tension",
    ),
    # Temperature (reserved for future)
    "room_thermostat": SensorDefinition(
        z2m_name="room_thermostat",
        device_type="temperature",
        properties=["temperature", "humidity"],
        primary_dimension="energy",  # temperature → ambient energy proxy
        description="Temperature sensor — future use",
    ),
}


# ------------------------------------------------------------------
# Dimension mapping table
# Maps Z2M payload keys → GTE dimension values
# ------------------------------------------------------------------

Z2M_TO_DIMENSION: dict[str, tuple[str, float, float]] = {
    # key                  dimension   scale   offset
    "occupancy":          ("presence", 1.0,    0.0),
    "illuminance_lux":    ("energy",   0.001,  0.0),  # lux → 0-1 (1000 lux = 1.0)
    "brightness":         ("energy",   1/255,  0.0),  # 0-255 → 0-1
    "temperature":        ("energy",   0.01,   0.0),   # °C → 0-1 (0-100°C range)
    "action_click":       ("tension",  1.0,    0.0),
    "action_hold":        ("tension",  1.0,    0.5),   # hold = higher tension
    "action_release":     ("tension",  1.0,   -0.3),   # release = tension drops
}


def z2m_payload_to_dimensions(payload: dict[str, Any]) -> dict[str, float]:
    """Convert a raw Z2M MQTT payload to GTE dimension values.

    Returns a dict of {dimension: value} for all dimensions present in payload.
    """
    result = {}
    for key, value in payload.items():
        if key in Z2M_TO_DIMENSION and isinstance(value, (int, float)):
            dimension, scale, offset = Z2M_TO_DIMENSION[key]
            result[dimension] = max(0.0, min(1.0, value * scale + offset))
    return result


# ------------------------------------------------------------------
# Default region boundaries for feeling states
# defined over [presence, energy, tension]
# ------------------------------------------------------------------

FEELING_REGION_BOUNDARIES: dict[str, dict[str, tuple[float, float]]] = {
    "Detecting": {
        "presence": (0.05, 1.0),
        "energy":   (0.0,  1.0),
        "tension":  (0.0,  0.3),
    },
    "Stabilizing": {
        "presence": (0.3,  1.0),
        "energy":   (0.2,  0.8),
        "tension":  (0.0,  0.2),
    },
    "Suspended": {
        "presence": (0.0,  0.15),
        "energy":   (0.0,  0.4),
        "tension":  (0.0,  0.15),
    },
    "Escalating": {
        "presence": (0.1,  1.0),
        "energy":   (0.4,  1.0),
        "tension":  (0.3,  1.0),
    },
    "Dispersing": {
        "presence": (0.0,  0.8),
        "energy":   (0.0,  0.6),
        "tension":  (0.1,  0.5),  # tension falling from peak
    },
}


# ------------------------------------------------------------------
# Notes
# ------------------------------------------------------------------
"""
TODO:
- Replace DEVICE_REGISTRY with live Z2M device list (fetched via REST API)
- Add temperature/humidity → ambient dimension mapping
- Consider motion direction (entering vs leaving) for presence delta
- Add battery level → health dimension (not in GTE yet)

REPLACEMENT STRATEGY:
  1. Fetch device list from Z2M REST API: GET /api/devices
  2. For each device, infer type from Z2M definition.exposes
  3. Auto-populate DEVICE_REGISTRY using Z2M_TO_DIMENSION lookup
  4. Keep FEELING_REGION_BOUNDARIES as human-curated constants
"""
