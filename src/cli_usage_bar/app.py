from __future__ import annotations

import logging
import subprocess
from datetime import UTC, datetime

import rumps

from cli_usage_bar import __version__
from cli_usage_bar.config import (
    CONFIG_PATH,
    Config,
    ensure_default_config,
    load_config,
)
from cli_usage_bar.models import UsageSnapshot
from cli_usage_bar.providers import ClaudeCodeProvider, CodexCliProvider, Provider
from cli_usage_bar.watcher import DebouncedWatcher

logger = logging.getLogger("cli_usage_bar")

BAR_LENGTH = 10
FILLED = "\u2593"  # ▓
EMPTY = "\u2591"   # ░


def bar(pct: float, length: int = BAR_LENGTH) -> str:
    filled = max(0, min(length, int(round((pct / 100.0) * length))))
    return FILLED * filled + EMPTY * (length - filled)


def format_reset(resets_at: datetime, now: datetime) -> str:
    delta = (resets_at - now).total_seconds()
    if delta <= 0:
        return "reset"
    hours, rem = divmod(int(delta), 3600)
    minutes = rem // 60
    if hours > 24:
        return f"in {hours // 24}d"
    if hours > 0:
        return f"in {hours}h{minutes:02d}m"
    return f"in {minutes}m"


class UsageBarApp(rumps.App):
    def __init__(self, config: Config) -> None:
        super().__init__("AI", title="AI", quit_button=None)
        self.config = config
        self.providers: list[Provider] = []
        if config.claude_code.enabled:
            self.providers.append(
                ClaudeCodeProvider(budget_tokens=config.claude_code.budget_tokens())
            )
        if config.codex_cli.enabled:
            self.providers.append(CodexCliProvider())

        self._build_menu()
        self.timer = rumps.Timer(self._on_tick, config.general.refresh_interval_sec)
        self.timer.start()

        watch_paths: list[str] = []
        for p in self.providers:
            watch_paths.extend(p.watch_paths())
        self.watcher = DebouncedWatcher(watch_paths, on_change=self._refresh_threadsafe)
        self.watcher.start()

        self.refresh()

    def _build_menu(self) -> None:
        self.status_items: dict[str, list[rumps.MenuItem]] = {}
        for p in self.providers:
            label = rumps.MenuItem(self._provider_title(p.name))
            label.set_callback(None)
            five_h = rumps.MenuItem("   5h: …")
            weekly = rumps.MenuItem("   weekly: …")
            extra = rumps.MenuItem("   ")
            self.menu.add(label)
            self.menu.add(five_h)
            self.menu.add(weekly)
            self.menu.add(extra)
            self.menu.add(None)  # separator
            self.status_items[p.name] = [label, five_h, weekly, extra]

        self.menu.add(rumps.MenuItem("Refresh now", callback=self._on_refresh_clicked))
        self.menu.add(rumps.MenuItem("Open config", callback=self._on_open_config))
        self.menu.add(None)
        self.menu.add(rumps.MenuItem(f"About v{__version__}", callback=self._on_about))
        self.menu.add(rumps.MenuItem("Quit", callback=self._on_quit))

    def _provider_title(self, name: str) -> str:
        return {
            "claude_code": "━━ Claude Code ━━",
            "codex_cli": "━━ Codex CLI ━━",
        }.get(name, f"━━ {name} ━━")

    def _on_tick(self, _sender) -> None:
        self.refresh()

    def _on_refresh_clicked(self, _sender) -> None:
        self.refresh()

    def _refresh_threadsafe(self) -> None:
        # rumps timer callbacks already run on main; watcher runs off-thread.
        # Schedule a one-shot timer from main thread via a tiny wrapper.
        try:
            rumps.Timer(lambda _s: self.refresh(), 0.1).start()
        except Exception:  # pragma: no cover
            logger.exception("refresh from watcher failed")

    def _on_open_config(self, _sender) -> None:
        path = ensure_default_config()
        subprocess.run(["open", str(path)], check=False)

    def _on_about(self, _sender) -> None:
        rumps.alert(
            title="cli-usage-bar",
            message=(
                f"Version {__version__}\n"
                "Reads Claude Code + Codex CLI local transcripts.\n"
                "https://github.com/svenedik/cli-usage-bar"
            ),
            ok="Close",
        )

    def _on_quit(self, _sender) -> None:
        self.watcher.stop()
        rumps.quit_application()

    def refresh(self) -> None:
        now = datetime.now(tz=UTC)
        title_parts: list[str] = []
        for p in self.providers:
            try:
                snap = p.snapshot()
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("provider %s crashed", p.name)
                snap = UsageSnapshot(provider=p.name, error=f"crashed: {exc}")
            self._render_provider(p.name, snap, now=now)
            if self.config.general.show_title_percent and snap.primary:
                prefix = "C" if p.name == "claude_code" else "X"
                title_parts.append(f"{prefix} {int(snap.primary.used_percent)}%")

        if title_parts:
            self.title = " | ".join(title_parts)
        else:
            self.title = "AI"

    def _render_provider(self, name: str, snap: UsageSnapshot, now: datetime) -> None:
        _label, five_h, weekly, extra = self.status_items[name]
        if snap.error:
            five_h.title = f"   {snap.error}"
            weekly.title = "   "
            extra.title = "   "
            return

        if snap.primary:
            pct = snap.primary.used_percent
            five_h.title = f"   5h: {bar(pct)} {pct:5.1f}%  ({format_reset(snap.primary.resets_at, now)})"
        else:
            five_h.title = "   5h: no active window"

        if snap.secondary:
            pct = snap.secondary.used_percent
            weekly.title = f"   weekly: {bar(pct)} {pct:5.1f}%  ({format_reset(snap.secondary.resets_at, now)})"
        else:
            weekly.title = "   weekly: —"

        extras: list[str] = []
        if snap.plan_type:
            extras.append(f"plan: {snap.plan_type}")
        if snap.cost_usd is not None and snap.cost_usd > 0:
            extras.append(f"cost: ${snap.cost_usd:.2f}")
        if snap.tokens_used:
            extras.append(f"tokens: {snap.tokens_used:,}")
        extra.title = "   " + ("  ·  ".join(extras) if extras else " ")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    if not CONFIG_PATH.exists():
        ensure_default_config()
    cfg = load_config()
    app = UsageBarApp(cfg)
    app.run()


if __name__ == "__main__":  # pragma: no cover
    main()
