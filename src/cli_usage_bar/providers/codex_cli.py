from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cli_usage_bar.models import RateLimit, UsageSnapshot
from cli_usage_bar.providers.base import Provider

DEFAULT_SESSIONS_DIR = Path.home() / ".codex" / "sessions"

# Only scan rollout files modified within this window. Anything older almost
# certainly carries stale rate-limit snapshots that would mislead the user.
_DEFAULT_LOOKBACK = timedelta(hours=24)


class CodexCliProvider(Provider):
    name = "codex_cli"

    def __init__(
        self,
        sessions_dir: Path = DEFAULT_SESSIONS_DIR,
        lookback: timedelta = _DEFAULT_LOOKBACK,
    ) -> None:
        self.sessions_dir = sessions_dir
        self.lookback = lookback

    def watch_paths(self) -> list[str]:
        return [str(self.sessions_dir)] if self.sessions_dir.exists() else []

    def snapshot(self) -> UsageSnapshot:
        if not self.sessions_dir.exists():
            return UsageSnapshot(
                provider=self.name,
                error=f"directory not found: {self.sessions_dir}",
            )

        cutoff = datetime.now(tz=UTC) - self.lookback
        candidates = _recent_rollouts(self.sessions_dir, cutoff=cutoff)
        if not candidates:
            return UsageSnapshot(
                provider=self.name,
                error=f"no rollouts modified in last {int(self.lookback.total_seconds() // 3600)}h",
            )

        latest_event, latest_ts = _scan_latest_token_count(candidates)
        if latest_event is None:
            return UsageSnapshot(
                provider=self.name,
                error="no token_count event in recent rollouts",
            )

        return _build_snapshot(latest_event, last_activity=latest_ts)


def _recent_rollouts(sessions_dir: Path, cutoff: datetime) -> list[Path]:
    rollouts: list[Path] = []
    for p in sessions_dir.rglob("rollout-*.jsonl"):
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=UTC)
        except OSError:
            continue
        if mtime >= cutoff:
            rollouts.append(p)
    return rollouts


def _scan_latest_token_count(paths: list[Path]) -> tuple[dict | None, datetime | None]:
    """Across ``paths``, find the token_count event with the newest timestamp.

    We can't trust ``file.mtime`` alone — a rollout written later may contain a
    token_count from earlier in its own timeline than another rollout's last
    token_count. We parse all candidates and compare embedded event timestamps.
    """
    best_event: dict | None = None
    best_ts: datetime | None = None

    for path in paths:
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    if '"token_count"' not in line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    payload = obj.get("payload") or {}
                    if payload.get("type") != "token_count":
                        continue
                    ts = _parse_iso(obj.get("timestamp"))
                    if ts is None:
                        continue
                    if best_ts is None or ts > best_ts:
                        best_ts = ts
                        best_event = payload
        except OSError:
            continue

    return best_event, best_ts


def _parse_iso(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def _build_snapshot(payload: dict, last_activity: datetime | None) -> UsageSnapshot:
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
