"""Base classes for output adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ...core.message import UniversalMessage


class BaseOutputAdapter(ABC):
    @abstractmethod
    def send(self, message: UniversalMessage):
        raise NotImplementedError

    @abstractmethod
    def status(self) -> dict:
        raise NotImplementedError
