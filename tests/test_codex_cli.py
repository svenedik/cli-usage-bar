from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from cli_usage_bar.providers.codex_cli import CodexCliProvider

FIXTURE = Path(__file__).parent / "fixtures" / "codex_rollout.jsonl"


def _layout_fixture(tmp_path: Path) -> Path:
    sessions = tmp_path / "sessions"
    day = sessions / "2026" / "04" / "16"
    day.mkdir(parents=True)
    dest = day / "rollout-2026-04-16T19-00-00-test.jsonl"
    shutil.copy(FIXTURE, dest)
    return sessions


def test_reads_latest_token_count(tmp_path):
    sessions = _layout_fixture(tmp_path)
    snap = CodexCliProvider(sessions_dir=sessions).snapshot()

    assert snap.error is None
    assert snap.provider == "codex_cli"
    assert snap.plan_type == "plus"
    assert snap.primary is not None
    assert snap.primary.used_percent == 17.5
    assert snap.primary.window_minutes == 300
    assert snap.primary.resets_at == datetime.fromtimestamp(1776379364, tz=UTC)
    assert snap.secondary is not None
    assert snap.secondary.used_percent == 22.0
    assert snap.tokens_used == 580


def test_missing_directory_returns_error(tmp_path):
    snap = CodexCliProvider(sessions_dir=tmp_path / "does-not-exist").snapshot()
    assert snap.error is not None
    assert snap.primary is None


def test_no_rollouts_returns_error(tmp_path):
    (tmp_path / "sessions").mkdir()
    snap = CodexCliProvider(sessions_dir=tmp_path / "sessions").snapshot()
    assert snap.error is not None
    assert "no rollouts" in snap.error


def test_picks_most_recent_file(tmp_path):
    sessions = tmp_path / "sessions" / "2026" / "04" / "16"
    sessions.mkdir(parents=True)
    older = sessions / "rollout-old.jsonl"
    newer = sessions / "rollout-new.jsonl"
    older.write_text(FIXTURE.read_text())
    newer.write_text(
        '{"timestamp":"2026-04-16T20:00:00.000Z","type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{"input_tokens":1,"cached_input_tokens":0,"output_tokens":1,"reasoning_output_tokens":0,"total_tokens":2}},"rate_limits":{"limit_id":"codex","primary":{"used_percent":99.0,"window_minutes":300,"resets_at":1776379999},"secondary":{"used_percent":50.0,"window_minutes":10080,"resets_at":1776762999},"plan_type":"pro"}}}\n'
    )
    import os

    os.utime(older, (1700000000, 1700000000))
    os.utime(newer, (1800000000, 1800000000))

    snap = CodexCliProvider(sessions_dir=tmp_path / "sessions").snapshot()
    assert snap.primary.used_percent == 99.0
    assert snap.plan_type == "pro"


def test_preferred_refresh_shortens_when_session_active(tmp_path):
    sessions = _layout_fixture(tmp_path)
    # Fixture's latest token_count timestamp is 2026-04-16T19:20:00 UTC.
    now = datetime(2026, 4, 16, 19, 20, 46, tzinfo=UTC)  # 46s after last event
    provider = CodexCliProvider(sessions_dir=sessions, now_fn=lambda: now)
    provider.snapshot()

    assert provider.preferred_refresh_interval(60) == 15
    assert provider.preferred_refresh_interval(5) == 5  # never slower than default


def test_preferred_refresh_uses_default_when_idle(tmp_path):
    sessions = _layout_fixture(tmp_path)
    # 10 minutes after last event — well past ACTIVE_SESSION_SECONDS (180).
    now = datetime(2026, 4, 16, 19, 30, 0, tzinfo=UTC)
    provider = CodexCliProvider(sessions_dir=sessions, now_fn=lambda: now)
    provider.snapshot()

    assert provider.preferred_refresh_interval(60) == 60


def test_preferred_refresh_default_before_first_snapshot(tmp_path):
    sessions = _layout_fixture(tmp_path)
    provider = CodexCliProvider(sessions_dir=sessions)
    # No snapshot() call yet → _last_event_ts is None → default applies.
    assert provider.preferred_refresh_interval(60) == 60


def test_timestamp_wins_over_mtime(tmp_path):
    """Newer file by mtime should lose if its token_count events are older."""
    sessions = tmp_path / "sessions" / "2026" / "04" / "17"
    sessions.mkdir(parents=True)

    # File A: written *later* (bigger mtime) but its last token_count is earlier
    a = sessions / "rollout-A.jsonl"
    a.write_text(
        '{"timestamp":"2026-04-17T05:00:00.000Z","type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{"total_tokens":1}},"rate_limits":{"primary":{"used_percent":10.0,"window_minutes":300,"resets_at":1776379999},"secondary":{"used_percent":5.0,"window_minutes":10080,"resets_at":1776762999},"plan_type":"plus"}}}\n'
    )

    # File B: written earlier, but contains a *later* token_count event
    b = sessions / "rollout-B.jsonl"
    b.write_text(
        '{"timestamp":"2026-04-17T09:00:00.000Z","type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{"total_tokens":1}},"rate_limits":{"primary":{"used_percent":77.0,"window_minutes":300,"resets_at":1776379999},"secondary":{"used_percent":44.0,"window_minutes":10080,"resets_at":1776762999},"plan_type":"plus"}}}\n'
    )

    import os
    now_ts = 1800000000
    os.utime(b, (now_ts - 3600, now_ts - 3600))
    os.utime(a, (now_ts, now_ts))

    from datetime import timedelta
    p = CodexCliProvider(sessions_dir=tmp_path / "sessions", lookback=timedelta(days=3650))
    snap = p.snapshot()
    # B's event (09:00) is newer than A's (05:00) → 77% wins
    assert snap.primary.used_percent == 77.0
