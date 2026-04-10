"""Base classes for real hardware adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ....core.message import UniversalMessage


class BaseInputAdapter(ABC):
    """Abstract base for all input adapters."""

    @abstractmethod
    def start(self):
        """Initialise and start the adapter."""
        raise NotImplementedError

    @abstractmethod
    def stop(self):
        """Stop and clean up the adapter."""
        raise NotImplementedError

    @abstractmethod
    def read(self) -> UniversalMessage | None:
        """Return the next message, or None if nothing ready."""
        raise NotImplementedError

    def status(self) -> dict[str, Any]:
        """Return a human-readable status dict."""
        return {"status": "ok"}


class BaseOutputAdapter(ABC):
    """Abstract base for all output adapters."""

    @abstractmethod
    def send(self, message: UniversalMessage):
        """Send a command to the hardware."""
        raise NotImplementedError

    def status(self) -> dict[str, Any]:
        """Return a human-readable status dict."""
        return {"status": "ok"}
