from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cli_usage_bar.models import RateLimit, UsageSnapshot
from cli_usage_bar.providers.claude_code_auto import ClaudeCodeAutoProvider


class _FakeProvider:
    def __init__(self, snap: UsageSnapshot, paths: list[str] | None = None) -> None:
        self._snap = snap
        self._paths = paths or []
        self.primary_override = None
        self.weekly_override = None
        self.manual_refreshes = 0

    def snapshot(self) -> UsageSnapshot:
        return self._snap

    def watch_paths(self) -> list[str]:
        return self._paths

    def set_budget_overrides(
        self,
        *,
        primary_budget_tokens: int | None = None,
        weekly_budget_tokens: int | None = None,
    ) -> bool:
        self.primary_override = primary_budget_tokens
        self.weekly_override = weekly_budget_tokens
        return True

    def preferred_refresh_interval(self, default_interval: int) -> int:
        return 15

    def on_manual_refresh(self) -> None:
        self.manual_refreshes += 1


def _rate_limit(percent: float) -> RateLimit:
    return RateLimit(
        used_percent=percent,
        window_minutes=300,
        resets_at=datetime(2026, 4, 18, tzinfo=UTC) + timedelta(hours=5),
    )


def test_api_snapshot_wins_when_available() -> None:
    api = _FakeProvider(
        UsageSnapshot(
            provider="claude_code",
            primary=_rate_limit(42),
            plan_type="Max (5x)",
        )
    )
    local = _FakeProvider(
        UsageSnapshot(
            provider="claude_code",
            primary=_rate_limit(41),
            secondary=_rate_limit(7),
            plan_type="Max (5x)",
            tokens_used=4_100_000,
            weekly_tokens_used=80_000_000,
        ),
        paths=["/tmp/claude-projects"],
    )

    provider = ClaudeCodeAutoProvider(api_provider=api, local_provider=local)
    snap = provider.snapshot()

    assert snap.primary is not None
    assert snap.primary.used_percent == 42
    assert provider.watch_paths() == ["/tmp/claude-projects"]
    assert local.primary_override == round(4_100_000 / (42 / 100.0))


def test_merge_uses_local_primary_when_api_primary_missing() -> None:
    api = _FakeProvider(
        UsageSnapshot(
            provider="claude_code",
            primary=None,
            secondary=_rate_limit(7),
            plan_type="Max (5x)",
        )
    )
    local = _FakeProvider(
        UsageSnapshot(
            provider="claude_code",
            primary=_rate_limit(35),
            plan_type="Max (5x)",
            tokens_used=2_500_000,
        )
    )
    provider = ClaudeCodeAutoProvider(api_provider=api, local_provider=local)
    snap = provider.snapshot()

    assert snap.primary is not None
    assert snap.primary.used_percent == 35
    assert snap.secondary is not None and snap.secondary.used_percent == 7
    assert snap.tokens_used == 2_500_000


def test_local_snapshot_falls_back_when_api_errors() -> None:
    api = _FakeProvider(
        UsageSnapshot(provider="claude_code", error="api: rate limited (try again shortly)")
    )
    local = _FakeProvider(
        UsageSnapshot(
            provider="claude_code",
            primary=_rate_limit(39),
            plan_type="Max (5x)",
        )
    )

    provider = ClaudeCodeAutoProvider(api_provider=api, local_provider=local)
    snap = provider.snapshot()

    assert snap.error is None
    assert snap.plan_type == "Max (5x)"
    assert snap.primary is not None
    assert snap.primary.used_percent == 39


def test_local_fallback_carries_api_last_sync() -> None:
    sync_dt = datetime(2026, 4, 17, 14, 30, tzinfo=UTC)
    api = _FakeProvider(
        UsageSnapshot(
            provider="claude_code",
            error="api: rate limited (try again shortly)",
            source="api",
            last_api_sync=sync_dt,
        )
    )
    local = _FakeProvider(
        UsageSnapshot(
            provider="claude_code",
            primary=_rate_limit(42),
            source="local",
        )
    )
    provider = ClaudeCodeAutoProvider(api_provider=api, local_provider=local)
    snap = provider.snapshot()
    assert snap.source == "local-fallback"
    assert snap.last_api_sync == sync_dt


def test_auto_provider_proxies_manual_refresh_and_interval() -> None:
    api = _FakeProvider(UsageSnapshot(provider="claude_code", error="api: no usage data"))
    local = _FakeProvider(UsageSnapshot(provider="claude_code", error="no recent usage messages"))

    provider = ClaudeCodeAutoProvider(api_provider=api, local_provider=local)

    assert provider.preferred_refresh_interval(60) == 15
    provider.on_manual_refresh()
    assert api.manual_refreshes == 1
