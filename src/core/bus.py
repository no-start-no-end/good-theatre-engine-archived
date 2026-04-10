"""
Message Bus for Good Theatre Engine.

Simple pub/sub bus for routing UniversalMessage objects.
"""
from collections import defaultdict
from typing import Callable

from .message import UniversalMessage, MessageType


class MessageBus:
    """
    Simple publish/subscribe message bus.

    Subscribers register for specific message types and receive all
    messages of that type.
    """

    def __init__(self):
        self._subscribers: dict[MessageType, list[Callable]] = defaultdict(list)

    def subscribe(self, message_type: MessageType, callback: Callable[[UniversalMessage], None]):
        """Register a callback for a message type."""
        self._subscribers[message_type].append(callback)

    def unsubscribe(self, message_type: MessageType, callback: Callable):
        """Remove a callback."""
        if callback in self._subscribers[message_type]:
            self._subscribers[message_type].remove(callback)

    def publish(self, message: UniversalMessage):
        """Deliver message to all subscribers of its type."""
        for callback in self._subscribers[message.type]:
            callback(message)

    def subscribe_all(self, callback: Callable[[UniversalMessage], None]):
        """Subscribe to all message types."""
        for message_type in MessageType:
            self.subscribe(message_type, callback)

    def clear(self):
        """Remove all subscribers."""
        self._subscribers.clear()
