"""File-system watcher with debounce. Falls back silently if watchdog is missing."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    _WATCHDOG_AVAILABLE = True
except ImportError:  # pragma: no cover - only if watchdog not installed
    _WATCHDOG_AVAILABLE = False


class DebouncedWatcher:
    def __init__(self, paths: list[str], on_change: Callable[[], None], debounce_sec: float = 2.0) -> None:
        self.paths = [p for p in paths if p and Path(p).exists()]
        self.on_change = on_change
        self.debounce_sec = debounce_sec
        self._observer = None
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def start(self) -> bool:
        if not _WATCHDOG_AVAILABLE or not self.paths:
            return False

        handler = _Handler(self._schedule)
        self._observer = Observer()
        for p in self.paths:
            self._observer.schedule(handler, p, recursive=True)
        self._observer.daemon = True
        self._observer.start()
        return True

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=1.0)
            self._observer = None
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None

    def _schedule(self) -> None:
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce_sec, self.on_change)
            self._timer.daemon = True
            self._timer.start()


if _WATCHDOG_AVAILABLE:

    class _Handler(FileSystemEventHandler):
        def __init__(self, callback: Callable[[], None]) -> None:
            super().__init__()
            self._cb = callback

        def on_modified(self, event) -> None:  # noqa: D401
            if not event.is_directory:
                self._cb()

        def on_created(self, event) -> None:  # noqa: D401
            if not event.is_directory:
                self._cb()
