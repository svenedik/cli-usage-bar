from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from cli_usage_bar.models import RateLimit, UsageSnapshot
from cli_usage_bar.providers.base import Provider

DEFAULT_SESSIONS_DIR = Path.home() / ".codex" / "sessions"


class CodexCliProvider(Provider):
    name = "codex_cli"

    def __init__(self, sessions_dir: Path = DEFAULT_SESSIONS_DIR) -> None:
        self.sessions_dir = sessions_dir

    def watch_paths(self) -> list[str]:
        return [str(self.sessions_dir)] if self.sessions_dir.exists() else []

    def snapshot(self) -> UsageSnapshot:
        if not self.sessions_dir.exists():
            return UsageSnapshot(
                provider=self.name,
                error=f"directory not found: {self.sessions_dir}",
            )
        latest_file = _latest_rollout(self.sessions_dir)
        if latest_file is None:
            return UsageSnapshot(provider=self.name, error="no rollout files found")
        event = _find_last_token_count(latest_file)
        if event is None:
            return UsageSnapshot(
                provider=self.name,
                error="no token_count event in latest rollout",
                last_activity=_file_mtime(latest_file),
            )
        return _build_snapshot(event, last_activity=_file_mtime(latest_file))


def _latest_rollout(sessions_dir: Path) -> Path | None:
    rollouts = list(sessions_dir.rglob("rollout-*.jsonl"))
    if not rollouts:
        return None
    return max(rollouts, key=lambda p: p.stat().st_mtime)


def _file_mtime(p: Path) -> datetime:
    return datetime.fromtimestamp(p.stat().st_mtime, tz=UTC)


def _find_last_token_count(path: Path) -> dict | None:
    """Return the payload of the most recent token_count event in the file."""
    last: dict | None = None
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or '"token_count"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = obj.get("payload") or {}
                if payload.get("type") == "token_count":
                    last = payload
    except OSError:
        return None
    return last


def _build_snapshot(payload: dict, last_activity: datetime) -> UsageSnapshot:
    rate = payload.get("rate_limits") or {}
    info = payload.get("info") or {}
    totals = info.get("total_token_usage") or {}

    primary = _build_rate_limit(rate.get("primary"))
    secondary = _build_rate_limit(rate.get("secondary"))

    return UsageSnapshot(
        provider="codex_cli",
        primary=primary,
        secondary=secondary,
        plan_type=rate.get("plan_type"),
        tokens_used=totals.get("total_tokens"),
        last_activity=last_activity,
    )


def _build_rate_limit(d: dict | None) -> RateLimit | None:
    if not d:
        return None
    used = d.get("used_percent")
    window = d.get("window_minutes")
    resets = d.get("resets_at")
    if used is None or window is None or resets is None:
        return None
    return RateLimit(
        used_percent=float(used),
        window_minutes=int(window),
        resets_at=datetime.fromtimestamp(int(resets), tz=UTC),
    )
