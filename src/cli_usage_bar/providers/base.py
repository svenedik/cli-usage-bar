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

    def preferred_refresh_interval(self, default_interval: int) -> int:
        """Return the preferred timer interval for this provider."""
        return default_interval

    def on_manual_refresh(self) -> None:
        """Allow a provider to override retry/backoff behavior on manual refresh."""
        return None
