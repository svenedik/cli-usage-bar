from __future__ import annotations

import logging

from cli_usage_bar.config import load_config


def test_load_config_ignores_unknown_keys(tmp_path, caplog):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[general]
refresh_interval_sec = 30
unknown = true

[claude_code]
plan_label = "Max (5x)"
extra = "ignored"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="cli_usage_bar.config"):
        config = load_config(path)

    assert config.general.refresh_interval_sec == 30
    assert config.claude_code.plan_label == "Max (5x)"
    assert "unknown config keys in [general]" in caplog.text
    assert "unknown config keys in [claude_code]" in caplog.text


def test_load_config_migrates_legacy_alert_thresholds(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[claude_code]
alert_primary_percent = 80

[codex_cli]
alert_secondary_percent = 70
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.claude_code.notifications_enabled is True
    assert config.codex_cli.notifications_enabled is True
