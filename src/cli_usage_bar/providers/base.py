from __future__ import annotations

from abc import ABC, abstractmethod

from cli_usage_bar.models import UsageSnapshot


class Provider(ABC):
    name: str

    @abstractmethod
    def snapshot(self) -> UsageSnapshot:
        """Return the current usage snapshot for this provider."""

    @abstractmethod
    def watch_paths(self) -> list[str]:
        """Directories to watch for filesystem changes that should trigger a refresh."""
