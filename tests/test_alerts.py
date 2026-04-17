from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cli_usage_bar.alerts import ProviderAlertState, next_provider_alert
from cli_usage_bar.models import RateLimit, UsageSnapshot


def _rate_limit(percent: float, *, hours: int) -> RateLimit:
    now = datetime(2026, 4, 17, 12, 0, tzinfo=UTC)
    return RateLimit(
        used_percent=percent,
        window_minutes=hours * 60,
        resets_at=now + timedelta(hours=hours),
    )


def test_primary_alert_fires_once_at_configured_threshold() -> None:
    state = ProviderAlertState()

    state, decision = next_provider_alert(
        UsageSnapshot(provider="claude_code", primary=_rate_limit(79, hours=5)),
        state,
        primary_threshold=80,
        secondary_threshold=95,
    )
    assert decision is None

    state, decision = next_provider_alert(
        UsageSnapshot(provider="claude_code", primary=_rate_limit(81, hours=5)),
        state,
        primary_threshold=80,
        secondary_threshold=95,
    )
    assert decision is not None
    assert decision.kind == "5h"
    assert decision.level == 80

    state, decision = next_provider_alert(
        UsageSnapshot(provider="claude_code", primary=_rate_limit(92, hours=5)),
        state,
        primary_threshold=80,
        secondary_threshold=95,
    )
    assert decision is None, "primary must not re-fire while still above threshold"


def test_primary_alert_rearms_after_drop_below() -> None:
    state = ProviderAlertState(primary_fired=True)

    state, decision = next_provider_alert(
        UsageSnapshot(provider="codex_cli", primary=_rate_limit(65, hours=5)),
        state,
        primary_threshold=70,
        secondary_threshold=95,
    )
    assert decision is None
    assert state.primary_fired is False

    state, decision = next_provider_alert(
        UsageSnapshot(provider="codex_cli", primary=_rate_limit(72, hours=5)),
        state,
        primary_threshold=70,
        secondary_threshold=95,
    )
    assert decision is not None
    assert decision.level == 70


def test_secondary_alert_fires_independently_from_primary() -> None:
    state = ProviderAlertState()
    snap = UsageSnapshot(
        provider="claude_code",
        primary=_rate_limit(50, hours=5),
        secondary=_rate_limit(96, hours=24 * 7),
    )

    state, decision = next_provider_alert(
        snap,
        state,
        primary_threshold=90,
        secondary_threshold=95,
    )
    assert decision is not None
    assert decision.kind == "weekly"
    assert decision.level == 95


def test_threshold_zero_disables_alert() -> None:
    state = ProviderAlertState()
    snap = UsageSnapshot(
        provider="claude_code",
        primary=_rate_limit(99, hours=5),
        secondary=_rate_limit(99, hours=24 * 7),
    )
    state, decision = next_provider_alert(
        snap,
        state,
        primary_threshold=0,
        secondary_threshold=0,
    )
    assert decision is None


def test_error_snapshot_produces_no_alert() -> None:
    state = ProviderAlertState()
    snap = UsageSnapshot(provider="claude_code", error="api: rate limited")
    state, decision = next_provider_alert(
        snap,
        state,
        primary_threshold=80,
        secondary_threshold=80,
    )
    assert decision is None


def test_primary_alert_does_not_refire_when_window_temporarily_missing() -> None:
    state = ProviderAlertState()

    state, decision = next_provider_alert(
        UsageSnapshot(provider="claude_code", primary=_rate_limit(92, hours=5)),
        state,
        primary_threshold=90,
        secondary_threshold=95,
    )
    assert decision is not None
    assert state.primary_fired is True

    # API returns only the weekly window; 5h is temporarily missing. The
    # primary fired flag must *not* reset — otherwise the next healthy tick
    # would duplicate the notification.
    state, decision = next_provider_alert(
        UsageSnapshot(provider="claude_code", secondary=_rate_limit(10, hours=24 * 7)),
        state,
        primary_threshold=90,
        secondary_threshold=95,
    )
    assert decision is None
    assert state.primary_fired is True

    state, decision = next_provider_alert(
        UsageSnapshot(provider="claude_code", primary=_rate_limit(93, hours=5)),
        state,
        primary_threshold=90,
        secondary_threshold=95,
    )
    assert decision is None, "must not re-fire after a single missing-field tick"


def test_primary_fires_before_secondary_on_same_tick() -> None:
    state = ProviderAlertState()
    snap = UsageSnapshot(
        provider="claude_code",
        primary=_rate_limit(91, hours=5),
        secondary=_rate_limit(96, hours=24 * 7),
    )
    state, decision = next_provider_alert(
        snap,
        state,
        primary_threshold=90,
        secondary_threshold=95,
    )
    assert decision is not None
    assert decision.kind == "5h"
    assert state.primary_fired is True
    assert state.secondary_fired is False

    state, decision = next_provider_alert(
        snap,
        state,
        primary_threshold=90,
        secondary_threshold=95,
    )
    assert decision is not None
    assert decision.kind == "weekly"
