"""Base classes for input adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ...core.message import UniversalMessage


class BaseInputAdapter(ABC):
    @abstractmethod
    def start(self):
        raise NotImplementedError

    @abstractmethod
    def stop(self):
        raise NotImplementedError

    @abstractmethod
    def read(self) -> UniversalMessage | None:
        raise NotImplementedError
