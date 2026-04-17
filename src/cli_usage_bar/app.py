from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import rumps

from cli_usage_bar import __version__
from cli_usage_bar.config import (
    CONFIG_PATH,
    Config,
    calibrate_from_dashboard,
    ensure_default_config,
    load_config,
)
from cli_usage_bar.models import RateLimit, UsageSnapshot
from cli_usage_bar.providers import ClaudeCodeProvider, CodexCliProvider, Provider
from cli_usage_bar.watcher import DebouncedWatcher

logger = logging.getLogger("cli_usage_bar")

BAR_LENGTH = 10
FILLED = "\u2593"  # ▓
EMPTY = "\u2591"   # ░

LAUNCH_AGENT_LABEL = "com.svenedik.cli-usage-bar"
LAUNCH_AGENT_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
LOG_PATH = Path("/tmp/cli-usage-bar.log")

CLAUDE_DASHBOARD_URL = "https://claude.ai/settings/usage"
CHATGPT_DASHBOARD_URL = "https://chatgpt.com/codex/cloud/settings/analytics"


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


def format_reset_short(resets_at: datetime, now: datetime) -> str:
    """Compact form for the menu bar title: "2h30m", "45m", "5d", or "reset"."""
    delta = (resets_at - now).total_seconds()
    if delta <= 0:
        return "reset"
    hours, rem = divmod(int(delta), 3600)
    minutes = rem // 60
    if hours >= 24:
        return f"{hours // 24}d"
    if hours > 0:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


def notify(title: str, message: str) -> None:
    """Send a macOS notification via osascript.

    osascript works without an app bundle, unlike rumps.notification which
    requires NSUserNotificationCenter registration that's unavailable when
    running plain `python -m cli_usage_bar`.
    """
    t = title.replace("\\", "\\\\").replace('"', '\\"')
    m = message.replace("\\", "\\\\").replace('"', '\\"')
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{m}" with title "{t}"'],
            check=False,
            timeout=3,
            capture_output=True,
        )
    except Exception:  # pragma: no cover
        logger.exception("osascript notification failed")


def launch_agent_state() -> str:
    """Return one of: 'missing' (no plist), 'enabled', 'disabled'."""
    if not LAUNCH_AGENT_PLIST.exists():
        return "missing"
    try:
        out = subprocess.run(
            ["launchctl", "print-disabled", f"gui/{os.getuid()}"],
            capture_output=True, text=True, check=False, timeout=3,
        ).stdout
    except Exception:  # pragma: no cover
        return "enabled"
    for line in out.splitlines():
        if LAUNCH_AGENT_LABEL in line:
            return "disabled" if "true" in line.lower() else "enabled"
    return "enabled"


def set_launch_agent_enabled(enabled: bool) -> None:
    action = "enable" if enabled else "disable"
    subprocess.run(
        ["launchctl", action, f"gui/{os.getuid()}/{LAUNCH_AGENT_LABEL}"],
        check=False, capture_output=True, timeout=3,
    )


class UsageBarApp(rumps.App):
    def __init__(self, config: Config) -> None:
        super().__init__("AI", title="AI", quit_button=None)
        self.config = config
        self.providers: list[Provider] = []
        if config.claude_code.enabled:
            self.providers.append(
                ClaudeCodeProvider(
                    budget_tokens=config.claude_code.budget_tokens(),
                    weekly_budget_tokens=config.claude_code.weekly_budget_tokens(),
                    plan_display=config.claude_code.plan_display(),
                )
            )
        if config.codex_cli.enabled:
            self.providers.append(CodexCliProvider())

        # (provider_name, kind) -> (last_block_resets_at, already_fired)
        self._alert_state: dict[tuple[str, str], tuple[datetime | None, bool]] = {}

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
            self.menu.add(None)
            self.status_items[p.name] = [label, five_h, weekly, extra]

        self.menu.add(rumps.MenuItem("Refresh now", callback=self._on_refresh_clicked))
        self.menu.add(
            rumps.MenuItem("Calibrate Claude Code…", callback=self._on_calibrate)
        )
        self.menu.add(None)
        self.menu.add(
            rumps.MenuItem("Claude Usage", callback=self._on_open_claude)
        )
        self.menu.add(
            rumps.MenuItem("Codex Analytics", callback=self._on_open_chatgpt)
        )
        self.menu.add(None)

        self.launch_at_login_item = rumps.MenuItem(
            "Launch at login", callback=self._on_toggle_launch_at_login
        )
        self._refresh_launch_at_login_state()
        self.menu.add(self.launch_at_login_item)
        self.menu.add(rumps.MenuItem("Open config", callback=self._on_open_config))
        self.menu.add(
            rumps.MenuItem("Copy diagnostic info", callback=self._on_copy_diagnostic)
        )
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
        # Manual refresh also picks up config.toml edits (labels, toggles).
        # Provider enable/disable + budget/plan changes still require app restart.
        try:
            self.config = load_config()
        except Exception:
            logger.exception("failed to reload config; keeping previous values")
        self.refresh()

    def _refresh_threadsafe(self) -> None:
        try:
            rumps.Timer(lambda _s: self.refresh(), 0.1).start()
        except Exception:  # pragma: no cover
            logger.exception("refresh from watcher failed")

    def _on_open_config(self, _sender) -> None:
        path = ensure_default_config()
        subprocess.run(["open", str(path)], check=False)

    def _on_open_claude(self, _sender) -> None:
        subprocess.run(["open", CLAUDE_DASHBOARD_URL], check=False)

    def _on_open_chatgpt(self, _sender) -> None:
        subprocess.run(["open", CHATGPT_DASHBOARD_URL], check=False)

    def _refresh_launch_at_login_state(self) -> None:
        state = launch_agent_state()
        if state == "missing":
            self.launch_at_login_item.title = "Launch at login (not installed)"
            self.launch_at_login_item.state = 0
        else:
            self.launch_at_login_item.title = "Launch at login"
            self.launch_at_login_item.state = 1 if state == "enabled" else 0

    def _on_toggle_launch_at_login(self, _sender) -> None:
        state = launch_agent_state()
        if state == "missing":
            rumps.alert(
                title="LaunchAgent not installed",
                message=(
                    "No plist at\n"
                    f"{LAUNCH_AGENT_PLIST}\n\n"
                    "Run install.sh once to register it."
                ),
                ok="Close",
            )
            return
        set_launch_agent_enabled(state == "disabled")
        self._refresh_launch_at_login_state()

    def _on_copy_diagnostic(self, _sender) -> None:
        text = self._build_diagnostic_report()
        try:
            subprocess.run(
                ["pbcopy"], input=text.encode("utf-8"), check=True, timeout=3
            )
            rumps.alert(
                title="Copied",
                message=(
                    "Diagnostic info is on your clipboard.\n"
                    "Paste it into your GitHub issue."
                ),
                ok="Close",
            )
        except Exception as exc:
            rumps.alert(title="Copy failed", message=str(exc), ok="Close")

    def _build_diagnostic_report(self) -> str:
        parts: list[str] = [
            f"cli-usage-bar v{__version__}",
            f"python: {sys.version.split()[0]}",
            f"platform: {platform.platform()}",
            f"launch_agent: {launch_agent_state()}",
            "",
            "--- config.toml ---",
            CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else "(missing)",
            "--- providers ---",
        ]
        for p in self.providers:
            try:
                snap = p.snapshot()
                parts.append(f"{p.name}:")
                parts.append(snap.model_dump_json(indent=2))
            except Exception as exc:  # pragma: no cover - defensive
                parts.append(f"{p.name}: ERROR {exc}")
        parts.append("")
        parts.append("--- last 40 log lines ---")
        try:
            if LOG_PATH.exists():
                lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
                parts.extend(lines)
            else:
                parts.append(f"(no log file at {LOG_PATH})")
        except Exception as exc:
            parts.append(f"(log read error: {exc})")
        return "\n".join(parts)

    def _on_calibrate(self, _sender) -> None:
        snap = self._latest_claude_snapshot()
        tokens = snap.tokens_used if snap and snap.tokens_used else 0
        if tokens <= 0:
            rumps.alert(
                title="No active block",
                message="Start or continue a Claude Code session first, then retry.",
                ok="Close",
            )
            return
        resp = rumps.Window(
            title="Calibrate Claude Code",
            message=(
                f"Active block tokens: {tokens:,}\n\n"
                "Open Claude.ai → Settings → Usage and copy the current\n"
                "session percentage (e.g. 51). Enter just the number below."
            ),
            default_text="",
            ok="Calibrate",
            cancel="Cancel",
            dimensions=(120, 24),
        ).run()
        if not resp.clicked:
            return
        try:
            pct = float(resp.text.strip().rstrip("%"))
        except ValueError:
            rumps.alert(title="Invalid input", message="Please enter a number like 51.")
            return
        if pct <= 0 or pct > 100:
            rumps.alert(title="Out of range", message="Percent must be between 0 and 100.")
            return
        budget = calibrate_from_dashboard(tokens_used=tokens, dashboard_percent=pct)
        rumps.alert(
            title="Calibrated",
            message=f"New Claude Code 5h budget: {budget:,} tokens.\nRefreshing…",
        )
        self.config = load_config()
        if self.providers and self.providers[0].name == "claude_code":
            self.providers[0] = ClaudeCodeProvider(
                budget_tokens=self.config.claude_code.budget_tokens(),
                weekly_budget_tokens=self.config.claude_code.weekly_budget_tokens(),
                plan_display=self.config.claude_code.plan_display(),
            )
        self.refresh()

    def _latest_claude_snapshot(self) -> UsageSnapshot | None:
        for p in self.providers:
            if p.name == "claude_code":
                try:
                    return p.snapshot()
                except Exception:
                    return None
        return None

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
            self._maybe_alert(p.name, snap)

            if not self.config.general.show_title_percent:
                continue
            provider_cfg = (
                self.config.claude_code if p.name == "claude_code" else self.config.codex_cli
            )
            pcts: list[str] = []
            show_reset = provider_cfg.title_show_reset
            if provider_cfg.title_show_primary and snap.primary:
                piece = f"{int(snap.primary.used_percent)}%"
                if show_reset:
                    piece += f" ({format_reset_short(snap.primary.resets_at, now)})"
                pcts.append(piece)
            if provider_cfg.title_show_secondary and snap.secondary:
                piece = f"{int(snap.secondary.used_percent)}%"
                if show_reset:
                    piece += f" ({format_reset_short(snap.secondary.resets_at, now)})"
                pcts.append(piece)
            if pcts:
                label = provider_cfg.title_label.strip()
                title_parts.append(f"{label} {' '.join(pcts)}".strip())

        if title_parts:
            self.title = " | ".join(title_parts)
        else:
            self.title = "AI"

    def _maybe_alert(self, provider_name: str, snap: UsageSnapshot) -> None:
        """Fire a macOS notification once per block when usage crosses a threshold."""
        provider_cfg = (
            self.config.claude_code if provider_name == "claude_code" else self.config.codex_cli
        )
        for kind, rl, threshold in (
            ("5h", snap.primary, provider_cfg.alert_primary_percent),
            ("weekly", snap.secondary, provider_cfg.alert_secondary_percent),
        ):
            self._maybe_alert_single(provider_name, kind, rl, threshold)

    def _maybe_alert_single(
        self, provider_name: str, kind: str, rl: RateLimit | None, threshold: int
    ) -> None:
        if rl is None or threshold <= 0:
            return
        key = (provider_name, kind)
        last_resets_at, fired = self._alert_state.get(key, (None, False))
        # New block (resets_at changed) ⇒ re-arm the alert.
        if last_resets_at != rl.resets_at:
            fired = False
        if not fired and rl.used_percent >= threshold:
            pretty = {"claude_code": "Claude Code", "codex_cli": "Codex CLI"}.get(
                provider_name, provider_name
            )
            notify(
                f"{pretty} · {kind}",
                f"Usage at {rl.used_percent:.0f}% (threshold {threshold}%).",
            )
            fired = True
        self._alert_state[key] = (rl.resets_at, fired)

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
        elif snap.cost_usd is not None and snap.cost_usd > 0:
            # Fall back to cost only when we don't have a plan label.
            extras.append(f"cost: ${snap.cost_usd:.2f}")
        if snap.tokens_used:
            if snap.budget_tokens:
                left = max(0, snap.budget_tokens - snap.tokens_used)
                extras.append(
                    f"tokens: {_fmt_tokens(snap.tokens_used)} / "
                    f"{_fmt_tokens(snap.budget_tokens)} "
                    f"({_fmt_tokens(left)} left)"
                )
            else:
                extras.append(f"tokens: {snap.tokens_used:,}")
        extra.title = "   " + ("  ·  ".join(extras) if extras else " ")


def _fmt_tokens(n: int) -> str:
    """Compact token formatting: 3_410_000 -> '3.41M', 45_000 -> '45K'."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


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
