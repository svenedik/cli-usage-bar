"""Claude Code usage provider.

Reads JSONL transcripts under ``~/.claude/projects/<slug>/<session-id>.jsonl`` and
aggregates usage into a ccusage-style 5-hour "block". A block starts at the
first message after >=5h inactivity and ends 5h later. The current block's
token counts drive the ``used_percent`` value displayed in the menubar.

Algorithm notes:
- Token total = ``input_tokens`` + ``cache_creation_input_tokens`` + ``output_tokens``
  (``cache_read_input_tokens`` is excluded because cache reads are essentially
  free and are typically not counted toward plan usage, matching ccusage).
- Only assistant messages with a ``message.usage`` block contribute.
- Files older than 24h are skipped entirely (optimization only; block start
  anchoring would need earlier data to be perfectly precise, but for a live
  display the last 24h is sufficient).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cli_usage_bar.models import RateLimit, UsageSnapshot
from cli_usage_bar.pricing import compute_cost
from cli_usage_bar.providers.base import Provider

DEFAULT_PROJECTS_DIR = Path.home() / ".claude" / "projects"
BLOCK_DURATION = timedelta(hours=5)
WEEK_DURATION = timedelta(days=7)


class ClaudeCodeProvider(Provider):
    name = "claude_code"

    def __init__(
        self,
        projects_dir: Path = DEFAULT_PROJECTS_DIR,
        budget_tokens: int = 7_500_000,
        weekly_budget_tokens: int | None = None,
        plan_display: str | None = None,
        now_fn=lambda: datetime.now(tz=UTC),
        lookback_hours: int = 24 * 7,
    ) -> None:
        self.projects_dir = projects_dir
        self.budget_tokens = budget_tokens
        self.weekly_budget_tokens = (
            weekly_budget_tokens if weekly_budget_tokens is not None else budget_tokens * 150
        )
        self._budget_override_tokens: int | None = None
        self._weekly_budget_override_tokens: int | None = None
        self.plan_display = plan_display
        self._now = now_fn
        self.lookback_hours = lookback_hours

    def watch_paths(self) -> list[str]:
        return [str(self.projects_dir)] if self.projects_dir.exists() else []

    def snapshot(self) -> UsageSnapshot:
        if not self.projects_dir.exists():
            return UsageSnapshot(
                provider=self.name,
                error=f"directory not found: {self.projects_dir}",
            )
        now = self._now()
        cutoff = now - timedelta(hours=self.lookback_hours)
        messages = list(_iter_usage_messages(self.projects_dir, cutoff=cutoff))
        if not messages:
            return UsageSnapshot(
                provider=self.name,
                error="no recent usage messages",
            )
        messages.sort(key=lambda m: m["timestamp"])

        current_block = _current_block(messages, now=now)
        weekly_messages = [m for m in messages if m["timestamp"] >= now - WEEK_DURATION]
        weekly_tokens = sum(m["tokens"] for m in weekly_messages)
        budget_tokens = self.current_budget_tokens()
        weekly_budget_tokens = self.current_weekly_budget_tokens()

        primary = _block_to_rate_limit(current_block, now=now, budget=budget_tokens)
        secondary = _weekly_rate_limit(
            weekly_tokens=weekly_tokens,
            budget=weekly_budget_tokens,
            now=now,
        )

        return UsageSnapshot(
            provider=self.name,
            primary=primary,
            secondary=secondary,
            plan_type=self.plan_display,
            tokens_used=current_block["tokens"] if current_block else 0,
            weekly_tokens_used=weekly_tokens,
            budget_tokens=budget_tokens,
            weekly_budget_tokens=weekly_budget_tokens,
            cost_usd=current_block["cost"] if current_block else 0.0,
            last_activity=messages[-1]["timestamp"],
            source="local",
        )

    def current_budget_tokens(self) -> int:
        return self._budget_override_tokens or self.budget_tokens

    def current_weekly_budget_tokens(self) -> int:
        return self._weekly_budget_override_tokens or self.weekly_budget_tokens

    def set_budget_overrides(
        self,
        *,
        primary_budget_tokens: int | None = None,
        weekly_budget_tokens: int | None = None,
    ) -> bool:
        changed = False
        if primary_budget_tokens and primary_budget_tokens > 0:
            if self._budget_override_tokens != primary_budget_tokens:
                self._budget_override_tokens = primary_budget_tokens
                changed = True
        if weekly_budget_tokens and weekly_budget_tokens > 0:
            if self._weekly_budget_override_tokens != weekly_budget_tokens:
                self._weekly_budget_override_tokens = weekly_budget_tokens
                changed = True
        return changed


def _iter_usage_messages(projects_dir: Path, cutoff: datetime) -> Iterator[dict]:
    for jsonl in projects_dir.rglob("*.jsonl"):
        try:
            mtime = datetime.fromtimestamp(jsonl.stat().st_mtime, tz=UTC)
        except OSError:
            continue
        if mtime < cutoff:
            continue
        try:
            with jsonl.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or '"usage"' not in line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    parsed = _parse_message(obj)
                    if parsed and parsed["timestamp"] >= cutoff:
                        yield parsed
        except OSError:
            continue


def _parse_message(obj: dict) -> dict | None:
    if obj.get("type") != "assistant":
        return None
    msg = obj.get("message") or {}
    usage = msg.get("usage") or {}
    if not usage:
        return None
    ts_str = obj.get("timestamp")
    if not ts_str:
        return None
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    model = msg.get("model") or "unknown"
    input_tokens = int(usage.get("input_tokens") or 0)
    cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    tokens = input_tokens + cache_creation + output_tokens
    cost = compute_cost(model, input_tokens, cache_creation, cache_read, output_tokens)
    return {
        "timestamp": ts,
        "model": model,
        "input": input_tokens,
        "cache_creation": cache_creation,
        "cache_read": cache_read,
        "output": output_tokens,
        "tokens": tokens,
        "cost": cost,
    }


def _current_block(messages: list[dict], now: datetime) -> dict | None:
    """Walk messages forward, building 5h blocks. Return the block active at ``now``.

    Block rules (mirroring ccusage):
    - A block starts at the first message, floored to the hour.
    - The block ends at ``start + 5h`` OR when a gap of >=5h occurs.
    - A new block starts when a message arrives after the previous block's end.
    """
    if not messages:
        return None

    block: dict | None = None
    prev_ts: datetime | None = None
    for m in messages:
        ts = m["timestamp"]
        if block is None:
            block = _new_block(ts)
        else:
            assert prev_ts is not None
            # Gap longer than block duration ⇒ new block
            if ts - prev_ts >= BLOCK_DURATION:
                block = _new_block(ts)
            # Natural block rollover
            elif ts >= block["end"]:
                block = _new_block(ts)
        _add_to_block(block, m)
        prev_ts = ts

    if block and now < block["end"] and (now - block["last_activity"]) < BLOCK_DURATION:
        return block
    return None


def _new_block(ts: datetime) -> dict:
    start = ts.replace(minute=0, second=0, microsecond=0)
    return {
        "start": start,
        "end": start + BLOCK_DURATION,
        "last_activity": ts,
        "tokens": 0,
        "cost": 0.0,
    }


def _add_to_block(block: dict, m: dict) -> None:
    block["tokens"] += m["tokens"]
    block["cost"] += m["cost"]
    block["last_activity"] = m["timestamp"]


def _aggregate(messages: list[dict]) -> tuple[int, float]:
    tokens = sum(m["tokens"] for m in messages)
    cost = sum(m["cost"] for m in messages)
    return tokens, round(cost, 4)


def _block_to_rate_limit(block: dict | None, now: datetime, budget: int) -> RateLimit | None:
    if block is None:
        return None
    pct = min(100.0, 100.0 * block["tokens"] / max(1, budget))
    return RateLimit(
        used_percent=round(pct, 2),
        window_minutes=int(BLOCK_DURATION.total_seconds() // 60),
        resets_at=block["end"],
    )


def _weekly_rate_limit(weekly_tokens: int, budget: int, now: datetime) -> RateLimit:
    # Local mode has no real "window start" — the 7d figure is a rolling
    # sum. Anchor resets_at to now+7d so it is monotonic; it's labelled "in
    # ~7d" in the UI. The API source (when enabled) provides the real value.
    pct = min(100.0, 100.0 * weekly_tokens / max(1, budget))
    return RateLimit(
        used_percent=round(pct, 2),
        window_minutes=int(WEEK_DURATION.total_seconds() // 60),
        resets_at=now + WEEK_DURATION,
    )
