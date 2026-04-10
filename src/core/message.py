"""
Universal Message Object for Good Theatre Engine.

All communication in the system flows through this schema.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
import uuid


class MessageType(Enum):
    SENSOR_EVENT = "sensor_event"
    AI_OUTPUT = "ai_output"
    HUMAN_INPUT = "human_input"
    SYSTEM = "system"
    OUTPUT_COMMAND = "output_command"
    ERROR = "error"
    HEARTBEAT = "heartbeat"


class Priority(Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class MessageMetadata:
    confidence: float = 1.0
    tags: list[str] = field(default_factory=list)
    trace_id: str | None = None
    parent_trace_id: str | None = None
    priority: Priority = Priority.NORMAL

    def to_dict(self) -> dict:
        return {
            "confidence": self.confidence,
            "tags": self.tags,
            "trace_id": self.trace_id,
            "parent_trace_id": self.parent_trace_id,
            "priority": self.priority.value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MessageMetadata":
        return cls(
            confidence=data.get("confidence", 1.0),
            tags=data.get("tags", []),
            trace_id=data.get("trace_id"),
            parent_trace_id=data.get("parent_trace_id"),
            priority=Priority(data.get("priority", "normal")),
        )


@dataclass
class UniversalMessage:
    """
    Universal Message Object.

    All inputs, outputs, and internal communication use this schema.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    type: MessageType = MessageType.SYSTEM
    source: str = "engine"
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: MessageMetadata = field(default_factory=MessageMetadata)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "type": self.type.value,
            "source": self.source,
            "payload": self.payload,
            "metadata": self.metadata.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UniversalMessage":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            timestamp=data.get("timestamp", datetime.now().timestamp()),
            type=MessageType(data.get("type", "system")),
            source=data.get("source", "unknown"),
            payload=data.get("payload", {}),
            metadata=MessageMetadata.from_dict(data.get("metadata", {})),
        )

    def with_trace(self, trace_id: str) -> "UniversalMessage":
        """Return a copy with updated trace."""
        self.metadata.trace_id = trace_id
        return self

    def with_parent_trace(self, parent_id: str) -> "UniversalMessage":
        """Return a copy referencing parent trace."""
        self.metadata.parent_trace_id = parent_id
        return self


# Convenience constructors


def sensor_event(
    source: str,
    payload: dict,
    confidence: float = 1.0,
    tags: list[str] | None = None,
) -> UniversalMessage:
    return UniversalMessage(
        type=MessageType.SENSOR_EVENT,
        source=source,
        payload=payload,
        metadata=MessageMetadata(
            confidence=confidence,
            tags=tags or [],
        ),
    )


def human_input(
    source: str,
    payload: dict,
    priority: Priority = Priority.NORMAL,
    tags: list[str] | None = None,
) -> UniversalMessage:
    return UniversalMessage(
        type=MessageType.HUMAN_INPUT,
        source=source,
        payload=payload,
        metadata=MessageMetadata(
            confidence=1.0,
            tags=tags or [],
            priority=priority,
        ),
    )


def ai_output(
    source: str,
    payload: dict,
    confidence: float = 0.9,
    tags: list[str] | None = None,
) -> UniversalMessage:
    return UniversalMessage(
        type=MessageType.AI_OUTPUT,
        source=source,
        payload=payload,
        metadata=MessageMetadata(
            confidence=confidence,
            tags=tags or [],
        ),
    )


def output_command(
    target: str,
    payload: dict,
    source: str = "engine",
) -> UniversalMessage:
    return UniversalMessage(
        type=MessageType.OUTPUT_COMMAND,
        source=source,
        payload={"target": target, **payload},
        metadata=MessageMetadata(tags=["output", target]),
    )
