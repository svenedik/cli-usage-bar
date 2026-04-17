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
    assert snap.error == "no rollout files found"


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
