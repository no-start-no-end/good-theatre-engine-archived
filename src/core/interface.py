"""Interface layer that logs, gates, and routes messages."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Callable

from .bus import MessageBus
from .knowledge import KnowledgeBase
from .message import MessageType, Priority, UniversalMessage


class InterfaceLayer:
    def __init__(self, bus: MessageBus, knowledge: KnowledgeBase, gate_mode: str = "advisory", log_dir: str | None = None):
        self.bus = bus
        self.knowledge = knowledge
        self.gate_mode = gate_mode
        self.log_dir = Path(log_dir or knowledge.storage_root / "events")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.event_log_path = self.log_dir / "events.jsonl"
        self.handlers: dict[MessageType, list[Callable[[UniversalMessage], None]]] = {}
        self.override_active = False

    def receive(self, message: UniversalMessage):
        if not message.metadata.trace_id:
            message.metadata.trace_id = message.id
        self.log_event(message)
        if self.gate_check(message):
            self.route(message)

    def route(self, message: UniversalMessage):
        self.bus.publish(message)
        for handler in self.handlers.get(message.type, []):
            handler(message)

    def register_handler(self, message_type: MessageType, handler: Callable[[UniversalMessage], None]):
        self.handlers.setdefault(message_type, []).append(handler)

    def log_event(self, message: UniversalMessage):
        entry = {
            "logged_at": datetime.utcnow().isoformat() + "Z",
            "trace_id": message.metadata.trace_id,
            "message": message.to_dict(),
        }
        with self.event_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def gate_check(self, message: UniversalMessage) -> bool:
        if self.gate_mode == "bypass":
            return True
        if self.gate_mode == "override":
            return message.type == MessageType.HUMAN_INPUT
        if self.gate_mode == "mandatory":
            critical = message.metadata.priority == Priority.CRITICAL or message.payload.get("critical")
            approved = message.payload.get("approved", False)
            return not critical or approved
        return True

    def set_gate_mode(self, mode: str):
        self.gate_mode = mode

    def replay_events(self) -> list[dict]:
        if not self.event_log_path.exists():
            return []
        with self.event_log_path.open("r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
